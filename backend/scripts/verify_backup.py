"""운영 백업이 실제로 복원되는지 격리 환경에서 확인한다(#270).

backend에서
  PYTHONPATH=. python scripts/verify_backup.py \
    --dump ~/backup/db-20261108-0300.sql \
    --documents ~/backup/documents-20261108-0300.tgz

운영 DB에는 붙지 않는다. DATABASE_URL을 읽지 않고, 검사용 MySQL을 새로 띄워 거기에만 넣는다.
복원한 표의 행 수와 서류 폴더 수를 세어, 백업 시점에 운영에서 센 값과 대조할 수 있게 낸다.
"""

import argparse
import json
import subprocess
import tarfile
from pathlib import Path

from sqlmodel import Session, create_engine, select
from testcontainers.community.mysql import MySqlContainer

from app.be.models.case import Case
from app.be.services.document import document_case_id

COUNTED_TABLES = ("members", "case", "case_history", "case_document_history", "blocker", "evidence")
DUMP_LAST_LINE = "-- Dump completed"


def check_files(dump: Path, documents: Path) -> dict:
    """지우기 전에 두 파일이 온전한지 먼저 본다(docs/deploy.md 5단계와 같은 검사)."""

    tail = dump.read_text(encoding="utf-8", errors="replace").rstrip().rsplit("\n", 1)[-1]
    with tarfile.open(documents, "r:gz") as archive:
        entries = archive.getnames()
    return {
        "dump_complete": tail.startswith(DUMP_LAST_LINE),
        "dump_last_line": tail[:60],
        "documents_readable": True,
        "document_entries": len(entries),
        "_entries": entries,
    }


def restore(container: MySqlContainer, dump: Path) -> None:
    """컨테이너 **안의** mysql로 넣는다.

    맥에 깔린 클라이언트가 5.7이면 8.0 서버에 붙지 못해 그대로 멈춘다(실측). 운영 절차도
    같은 이유로 `$C exec -T mysql mysql ...`을 쓴다(docs/deploy.md).
    """

    subprocess.run(
        ["docker", "exec", "-i", container.get_wrapped_container().id,
         "mysql", "--user", "root", f"--password={container.root_password}",
         "--default-character-set=utf8mb4", container.dbname],
        stdin=dump.open("rb"), check=True, capture_output=True,
    )


def count_rows(engine) -> dict[str, int]:
    from sqlalchemy import text
    with Session(engine) as session:
        return {
            name: session.exec(text(f"SELECT COUNT(*) FROM `{name}`")).one()[0]
            for name in COUNTED_TABLES
        }


def match_documents(engine, entries: list[str]) -> dict:
    """DB의 Case마다 기대하는 서류 폴더가 압축 안에 있는지 본다.

    폴더 이름은 Case 번호가 아니라 번호와 만든 시각으로 만든 UUID다(document_case_id).
    둘이 어긋나면 DB와 서류를 같이 되돌려도 서로 짝이 안 맞는다.
    """

    folders = {name.split("/")[1] for name in entries if name.startswith("./") and "/" in name[2:]}
    with Session(engine) as session:
        cases = session.exec(select(Case)).all()
        expected = {str(document_case_id(case)): case.id for case in cases}
    found = sorted(expected[f] for f in folders if f in expected)
    return {
        "case_count": len(expected),
        "document_folder_count": len(folders),
        "cases_with_documents": found,
        "folders_without_case": sorted(folders - set(expected)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    args = parser.parse_args()

    files = check_files(args.dump, args.documents)
    entries = files.pop("_entries")
    if not files["dump_complete"]:
        print(json.dumps({"files": files, "restored": False,
                          "reason": "덤프 마지막 줄이 완료 표시가 아니다. 복원하지 않는다"},
                         ensure_ascii=False, indent=2))
        return

    with MySqlContainer("mysql:8.0", dialect="pymysql", username="test", password="test",
                        root_password="test", dbname="backup_check").with_env("TZ", "Asia/Seoul") as container:
        restore(container, args.dump)
        engine = create_engine(container.get_connection_url() + "?charset=utf8mb4")
        try:
            result = {"files": files, "restored": True,
                      "rows": count_rows(engine), "documents": match_documents(engine, entries)}
        finally:
            engine.dispose()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
