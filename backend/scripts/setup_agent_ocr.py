"""Download Korean/English OCR language data once; Agent requests stay offline.

Install document dependencies first:
  pip install -r backend/app/agent/document_tool/requirements.txt
Then run this script. No sudo or system package changes are required.
"""

import argparse
import hashlib
import json
from pathlib import Path

import httpx

TESSDATA_REVISION = "87416418657359cb625c412a48b6e1d6d41c29bd"
LANGUAGE_SHA256 = {
    "kor": "6b85e11d9bbf07863b97b3523b1b112844c43e713df8b66418a081fd1060b3b2",
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
}


def setup(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for language in ("kor", "eng"):
            path = directory / f"{language}.traineddata"
            expected = LANGUAGE_SHA256[language]
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                response = client.get(
                    f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{TESSDATA_REVISION}/{language}.traineddata"
                )
                response.raise_for_status()
                if not 1_000 < len(response.content) < 30_000_000:
                    raise ValueError("Unexpected OCR language file size")
                if hashlib.sha256(response.content).hexdigest() != expected:
                    raise ValueError("OCR language file checksum differs from the pinned revision")
                pending = path.with_suffix(".tmp")
                pending.write_bytes(response.content)
                pending.replace(path)
            manifest[language] = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Local OCR ready: {directory}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path.home() / ".cache/reborn/tessdata")
    setup(parser.parse_args().directory)
