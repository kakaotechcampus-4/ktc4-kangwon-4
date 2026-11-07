"""백업 검증 스크립트가 실제 덤프·압축으로 도는지 본다(#270).

진짜 백업이 오기 전에, 같은 방법(mysqldump + tar)으로 만든 합성 백업으로 확인한다.
운영 DB에는 붙지 않는다.
"""

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from app.be.models.case import Case
from app.be.services.document import document_case_id
from scripts import verify_backup
from case_world import case_engine, case_world  # noqa: F401 — 픽스처


def container_publishing(port: int) -> str:
    """그 호스트 포트를 여는 컨테이너를 찾는다.

    `--filter publish=`는 컨테이너 안쪽 포트를 보기 때문에 로컬 개발 DB(3306)까지 걸린다.
    검사용 컨테이너만 집으려고 호스트 포트를 그대로 맞춰 본다.
    """

    listed = subprocess.run(["docker", "ps", "--format", "{{.ID}} {{.Ports}}"],
                            capture_output=True, text=True, check=True).stdout.splitlines()
    found = [line.split()[0] for line in listed if f":{port}->" in line]
    assert len(found) == 1, f"호스트 포트 {port}를 여는 컨테이너가 {len(found)}개다"
    return found[0]


def dump_from(engine, path: Path) -> None:
    """deploy.md 2단계와 같은 옵션으로, 컨테이너 안의 mysqldump로 받는다."""
    url = engine.url
    with path.open("wb") as out:
        subprocess.run(
            ["docker", "exec", container_publishing(url.port),
             "mysqldump", "--user", "root", "--password=test",
             "--single-transaction", "--default-character-set=utf8mb4", url.database],
            stdout=out, check=True, stderr=subprocess.DEVNULL,
        )


def documents_tgz(path: Path, folders: list[str]) -> None:
    """운영의 `tar czf - -C /data/documents .`와 같은 모양으로 만든다."""
    root = path.parent / "documents"
    for folder in folders:
        (root / folder).mkdir(parents=True, exist_ok=True)
        (root / folder / "context.json").write_text("{}", encoding="utf-8")
    with tarfile.open(path, "w:gz") as archive:
        archive.add(root, arcname=".")


@pytest.fixture
def backup(tmp_path, case_engine, case_world):  # noqa: F811
    """합성 Case로 덤프와 서류 압축을 만들고, **덤프 시점의 개수**를 같이 돌려준다.

    #270이 운영에서 하는 일과 같다 — 백업을 뜬 그 순간의 값이 있어야 복원 결과를 대조할 수 있다.
    """

    _, case_id, _ = case_world.sign_up()
    with Session(case_engine) as session:
        case = session.get(Case, case_id)
        folder = str(document_case_id(case))
    dump = tmp_path / "db.sql"
    documents = tmp_path / "documents.tgz"
    dump_from(case_engine, dump)
    source_rows = verify_backup.count_rows(case_engine)
    documents_tgz(documents, [folder, str(uuid4())])  # 짝 있는 폴더 하나, 없는 폴더 하나
    return dump, documents, {"rows": source_rows, "case_id": case_id}


def test_truncated_dump_is_refused_before_restoring(backup, tmp_path):
    dump, documents, _ = backup
    cut = tmp_path / "cut.sql"
    cut.write_text(dump.read_text(encoding="utf-8")[:2000], encoding="utf-8")

    files = verify_backup.check_files(cut, documents)

    assert files["dump_complete"] is False


def test_real_dump_restores_and_counts_match(backup, case_engine):  # noqa: F811
    dump, documents, source = backup
    files = verify_backup.check_files(dump, documents)
    assert files["dump_complete"] is True

    result = subprocess.run(
        [sys.executable, "scripts/verify_backup.py", "--dump", str(dump), "--documents", str(documents)],
        cwd=Path(__file__).resolve().parents[1], env={**os.environ, "PYTHONPATH": "."},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout)

    assert report["restored"] is True
    # 복원한 쪽이 덤프 시점과 같은지 — #270의 "운영 백업 시점 값과 비교"가 이것이다
    assert report["rows"] == source["rows"]
    assert source["case_id"] in report["documents"]["cases_with_documents"]
    assert len(report["documents"]["folders_without_case"]) == 1
