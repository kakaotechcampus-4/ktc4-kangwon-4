"""Offline Chroma index for unreviewed official-notice discovery only.

The caller supplies every document and embedding. This adapter never contacts
an embedding provider, creates policy rules, or reads the application database.
Persistence is a separate local Chroma artifact. The configured directory must
already exist and be controlled by the offline job, not another writer.
"""

from __future__ import annotations

import fcntl
import math
import os
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from app.agent.support_agent.wiki.store import _root_descriptor

_COLLECTION = "reborn_support_discovery_v1"
_MAX_CHUNKS = 1000
_ADD_BATCH_SIZE = 32
_MAX_DIRECTORY_ENTRIES = 4096
_FLOAT32_MAX = 3.4028234663852886e38
_SQLITE_FILE = "chroma.sqlite3"

MetadataValue = str | int | float | bool


class DiscoveryIndexError(RuntimeError):
    """Sanitized index failure without document, path, or provider details."""


@dataclass(frozen=True, slots=True)
class IndexRecord:
    chunk_id: str
    text: str
    metadata: dict[str, MetadataValue]


@dataclass(frozen=True, slots=True)
class IndexHit:
    chunk_id: str
    distance: float


def _nonempty(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _metadata(
    embedding_model: str, dimensions: int, corpus_digest: str
) -> dict[str, MetadataValue]:
    if (
        not _nonempty(embedding_model)
        or type(dimensions) is not int
        or not 1 <= dimensions <= 65536
        or not _nonempty(corpus_digest)
    ):
        raise DiscoveryIndexError("discovery index configuration is invalid")
    return {
        "embedding_model": embedding_model,
        "dimensions": dimensions,
        "corpus_digest": corpus_digest,
        "review_status": "UNREVIEWED",
    }


def _vector(value: Sequence[float], dimensions: int) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DiscoveryIndexError("discovery vector must be a numeric sequence")
    if len(value) != dimensions:
        raise DiscoveryIndexError("discovery vector dimensions do not match")
    if any(
        type(item) not in {int, float}
        or not math.isfinite(item)
        or abs(item) > _FLOAT32_MAX
        for item in value
    ):
        raise DiscoveryIndexError("discovery vector contains invalid values")
    if not any(value):
        raise DiscoveryIndexError("cosine discovery vector must be nonzero")
    return [float(item) for item in value]


def _inspect_tree(directory: int, remaining: list[int]) -> None:
    """Inspect persisted files via descriptors without following symlinks."""

    with os.scandir(directory) as entries:
        for entry in entries:
            remaining[0] -= 1
            if remaining[0] < 0:
                raise DiscoveryIndexError("discovery index directory is too large")
            details = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(details.st_mode):
                child = os.open(
                    entry.name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory,
                )
                try:
                    _inspect_tree(child, remaining)
                finally:
                    os.close(child)
            elif not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                raise DiscoveryIndexError("discovery index contains unsafe files")


@contextmanager
def _directory(
    path: Path,
    *,
    identity: tuple[int, int] | None = None,
    require_database: bool = False,
    exclusive: bool = False,
) -> Iterator[tuple[int, int]]:
    try:
        with _root_descriptor(path) as descriptor:
            lock = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(descriptor, lock | fcntl.LOCK_NB)
            details = os.fstat(descriptor)
            current = (details.st_dev, details.st_ino)
            if identity is not None and current != identity:
                raise DiscoveryIndexError("discovery index directory changed")
            _inspect_tree(descriptor, [_MAX_DIRECTORY_ENTRIES])
            if require_database:
                database = os.open(
                    _SQLITE_FILE,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=descriptor,
                )
                with os.fdopen(database, "rb") as source:
                    if source.read(16) != b"SQLite format 3\x00":
                        raise DiscoveryIndexError(
                            "an existing discovery index database is required"
                        )
            yield current
    except DiscoveryIndexError:
        raise
    except (OSError, RecursionError):
        raise DiscoveryIndexError(
            "discovery index directory could not be accessed safely"
        ) from None


def _client(path: Path) -> Any:
    # Lazy imports keep the optional offline dependency out of Agent startup.
    import chromadb
    from chromadb.config import Settings

    return chromadb.PersistentClient(
        path=str(path),
        settings=Settings(
            chroma_api_impl="chromadb.api.rust.RustBindingsAPI",
            anonymized_telemetry=False,
            chroma_otel_collection_endpoint="",
            chroma_otel_collection_headers={},
            chroma_otel_granularity="none",
            allow_reset=False,
        ),
    )


class ChromaDiscoveryIndex:
    """A bounded, supplied-vector index; never an eligibility data source."""

    def __init__(
        self,
        path: Path,
        metadata: dict[str, MetadataValue],
        client: Any,
        collection: Any,
        identity: tuple[int, int],
    ) -> None:
        self._path = path
        self._metadata = metadata
        self._dimensions = int(metadata["dimensions"])
        self._client = client
        self._collection = collection
        self._identity = identity

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        embedding_model: str,
        dimensions: int,
        corpus_digest: str,
    ) -> Self:
        """Create the fixed collection, refusing an existing collection."""

        metadata = _metadata(embedding_model, dimensions, corpus_digest)
        try:
            root = Path(os.path.abspath(path))
            with _directory(root, exclusive=True) as identity:
                client = _client(root)
                collection = client.create_collection(
                    name=_COLLECTION,
                    metadata=metadata,
                    configuration={"hnsw": {"space": "cosine"}},
                    embedding_function=None,
                    get_or_create=False,
                )
                result = cls(root, metadata, client, collection, identity)
                result._check_collection()
                return result
        except DiscoveryIndexError:
            raise
        except Exception:  # noqa: BLE001 - Chroma errors may expose local paths
            raise DiscoveryIndexError(
                "discovery index could not be created without replacement"
            ) from None

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        embedding_model: str,
        dimensions: int,
        corpus_digest: str,
    ) -> Self:
        """Read an existing collection; never create a missing database."""

        metadata = _metadata(embedding_model, dimensions, corpus_digest)
        try:
            root = Path(os.path.abspath(path))
            with _directory(root, require_database=True) as identity:
                client = _client(root)
                collection = client.get_collection(
                    name=_COLLECTION, embedding_function=None
                )
                result = cls(root, metadata, client, collection, identity)
                result._check_collection()
                result._checked_count()
                return result
        except DiscoveryIndexError:
            raise
        except Exception:  # noqa: BLE001 - Chroma errors may expose local paths
            raise DiscoveryIndexError(
                "existing discovery index could not be opened"
            ) from None

    def _check_collection(self) -> None:
        actual = self._collection.metadata
        if not isinstance(actual, dict) or any(
            type(actual.get(key)) is not type(value) or actual.get(key) != value
            for key, value in self._metadata.items()
        ):
            raise DiscoveryIndexError("discovery index provenance does not match")
        # The parsed configuration property may construct embedding providers.
        # Inspect raw configuration instead, accepting only no embedding function.
        configuration = self._collection.configuration_json
        if (
            not isinstance(configuration, dict)
            or not isinstance(configuration.get("hnsw"), dict)
            or configuration["hnsw"].get("space") != "cosine"
            or configuration.get("embedding_function") not in (None, {"type": "legacy"})
        ):
            raise DiscoveryIndexError("discovery index configuration does not match")

    def _checked_count(self) -> int:
        count = self._collection.count()
        if type(count) is not int or not 0 <= count <= _MAX_CHUNKS:
            raise DiscoveryIndexError("discovery index exceeds its corpus limit")
        return count

    def add(
        self,
        records: Sequence[IndexRecord],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        """Validate the whole addition, then write batches of at most 32."""

        try:
            if not 1 <= len(records) <= _MAX_CHUNKS or len(records) != len(vectors):
                raise DiscoveryIndexError(
                    "discovery record and vector counts are invalid"
                )
            ids: list[str] = []
            documents: list[str] = []
            metadatas: list[dict[str, MetadataValue]] = []
            for record in records:
                if (
                    not isinstance(record, IndexRecord)
                    or not _nonempty(record.chunk_id)
                    or not _nonempty(record.text)
                    or not isinstance(record.metadata, dict)
                    or not _nonempty(record.metadata.get("external_notice_id"))
                ):
                    raise DiscoveryIndexError("discovery record failed its contract")
                metadata = dict(record.metadata)
                if any(
                    not _nonempty(key)
                    or type(value) not in {str, int, float, bool}
                    or (type(value) is float and not math.isfinite(value))
                    for key, value in metadata.items()
                ):
                    raise DiscoveryIndexError("discovery metadata failed its contract")
                if metadata.get("review_status", "UNREVIEWED") != "UNREVIEWED":
                    raise DiscoveryIndexError(
                        "discovery records must remain unreviewed"
                    )
                metadata["review_status"] = "UNREVIEWED"
                ids.append(record.chunk_id)
                documents.append(record.text)
                metadatas.append(metadata)
            if len(set(ids)) != len(ids):
                raise DiscoveryIndexError("discovery chunk identifiers must be unique")
            embeddings = [_vector(vector, self._dimensions) for vector in vectors]
            with _directory(
                self._path,
                identity=self._identity,
                require_database=True,
                exclusive=True,
            ):
                self._check_collection()
                previous_count = self._checked_count()
                if previous_count + len(ids) > _MAX_CHUNKS:
                    raise DiscoveryIndexError(
                        "discovery index exceeds its corpus limit"
                    )
                if self._collection.get(ids=ids, include=[])["ids"]:
                    raise DiscoveryIndexError(
                        "discovery chunk identifiers already exist"
                    )
                for offset in range(0, len(ids), _ADD_BATCH_SIZE):
                    end = offset + _ADD_BATCH_SIZE
                    self._collection.add(
                        ids=ids[offset:end],
                        embeddings=embeddings[offset:end],
                        documents=documents[offset:end],
                        metadatas=metadatas[offset:end],
                    )
                if self._checked_count() != previous_count + len(ids):
                    raise DiscoveryIndexError("discovery index row count did not match")
        except DiscoveryIndexError:
            raise
        except Exception:  # noqa: BLE001 - never surface document/provider details
            # Batches are not a transaction. The caller must not publish its
            # manifest after any failed addition, including partial I/O failure.
            raise DiscoveryIndexError("discovery records could not be added") from None

    def search(
        self,
        vector: Sequence[float],
        *,
        limit: int = 5,
        external_notice_id: str | None = None,
    ) -> list[IndexHit]:
        try:
            if type(limit) is not int or not 1 <= limit <= 10:
                raise DiscoveryIndexError(
                    "discovery search limit must be between 1 and 10"
                )
            if external_notice_id is not None and not _nonempty(external_notice_id):
                raise DiscoveryIndexError("discovery notice filter is invalid")
            embedding = _vector(vector, self._dimensions)
            where: dict[str, Any] = {"review_status": "UNREVIEWED"}
            if external_notice_id is not None:
                where = {"$and": [where, {"external_notice_id": external_notice_id}]}
            with _directory(self._path, identity=self._identity, require_database=True):
                self._check_collection()
                count = self._checked_count()
                if not count:
                    return []
                result = self._collection.query(
                    query_embeddings=[embedding],
                    n_results=min(limit, count),
                    where=where,
                    include=["distances"],
                )
            ids, distances = result.get("ids"), result.get("distances")
            if (
                not isinstance(ids, list)
                or not isinstance(distances, list)
                or len(ids) != 1
                or len(distances) != 1
                or not isinstance(ids[0], list)
                or not isinstance(distances[0], list)
                or len(ids[0]) != len(distances[0])
                or len(ids[0]) > limit
                or any(not _nonempty(identifier) for identifier in ids[0])
                or len(set(ids[0])) != len(ids[0])
                or any(
                    type(distance) not in {int, float} or not math.isfinite(distance)
                    for distance in distances[0]
                )
            ):
                raise DiscoveryIndexError(
                    "discovery search response failed its contract"
                )
            return [
                IndexHit(chunk_id=identifier, distance=float(distance))
                for identifier, distance in zip(ids[0], distances[0], strict=True)
            ]
        except DiscoveryIndexError:
            raise
        except Exception:  # noqa: BLE001 - never surface query/provider details
            raise DiscoveryIndexError("discovery index search failed") from None

    def count(self) -> int:
        try:
            with _directory(self._path, identity=self._identity, require_database=True):
                self._check_collection()
                return self._checked_count()
        except DiscoveryIndexError:
            raise
        except Exception:  # noqa: BLE001 - Chroma errors may expose local paths
            raise DiscoveryIndexError("discovery index count failed") from None


__all__ = ["ChromaDiscoveryIndex", "DiscoveryIndexError", "IndexHit", "IndexRecord"]
