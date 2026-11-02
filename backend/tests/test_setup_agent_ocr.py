import hashlib
import json

import httpx
import pytest
from scripts import setup_agent_ocr as module


def configure(monkeypatch, *, valid=True):
    data = {language: (language.encode() * 1000) for language in ("kor", "eng")}
    monkeypatch.setattr(module, "LANGUAGE_SHA256", {
        language: hashlib.sha256(value).hexdigest() for language, value in data.items()
    })
    requests = []
    client = httpx.Client

    def handle(request):
        requests.append(str(request.url))
        language = request.url.path.rsplit("/", 1)[1].split(".")[0]
        return httpx.Response(200, content=data[language] if valid else b"invalid" * 1000)

    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs))
    return data, requests


def test_setup_pins_downloads_checks_cached_files_and_repairs_corruption(tmp_path, monkeypatch):
    data, requests = configure(monkeypatch)
    module.setup(tmp_path)
    assert len(requests) == 2 and all(module.TESSDATA_REVISION in url and "/main/" not in url for url in requests)
    module.setup(tmp_path)
    assert len(requests) == 2
    (tmp_path / "kor.traineddata").write_bytes(b"corrupted")
    module.setup(tmp_path)
    assert len(requests) == 3 and (tmp_path / "kor.traineddata").read_bytes() == data["kor"]
    assert json.loads((tmp_path / "manifest.json").read_text()) == module.LANGUAGE_SHA256


def test_setup_does_not_store_a_file_with_the_wrong_checksum(tmp_path, monkeypatch):
    configure(monkeypatch, valid=False)
    with pytest.raises(ValueError, match="checksum"):
        module.setup(tmp_path)
    assert not list(tmp_path.iterdir())
