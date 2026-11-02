"""Download Korean/English OCR language data once; Agent requests stay offline.

Install document dependencies first:
  pip install -r backend/app/agent/document_agent/requirements.txt
Then run this script. No sudo or system package changes are required.
"""

import argparse
import hashlib
import json
from pathlib import Path

import httpx


def setup(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for language in ("kor", "eng"):
            path = directory / f"{language}.traineddata"
            if not path.is_file():
                response = client.get(
                    f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{language}.traineddata"
                )
                response.raise_for_status()
                if not 1_000 < len(response.content) < 30_000_000:
                    raise ValueError("Unexpected OCR language file size")
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
