"""
핵심 연관관계가 실제로 동작하는지 검증하는 스크립트.

SHOW TABLES로는 "테이블이 만들어졌는지"만 확인되고, FK가 올바른 대상을 가리키는지,
Relationship(back_populates)으로 이어둔 객체 탐색이 실제 데이터로 동작하는지는
직접 데이터를 넣고 조회해봐야 확인할 수 있다.

확인 범위 (핵심 관계만):
  1. members -> case            (member_id FK)
  2. case -> case_history        (case_id FK)
  3. case_history <-> blocker    (순환 참조: created_from_case_log_id, priority_blocker_id)
  4. case_history -> case_field_change (case_history_id FK)

주의: 이 스크립트는 테스트용 데이터를 실제로 insert했다가 마지막에 전부 삭제한다.
      절대 배포/운영 DB에 실행하지 말 것. 로컬 개발 DB에서만 사용.

사용법:
    cd backend
    python -m scripts.verify_relations
"""
from sqlmodel import Session, select

from app.core.database import engine
from app.be.models import Member, Case, CaseHistory, CaseFieldChange, Blocker


def verify_relations() -> None:
    with Session(engine) as session:
        print("=== 1. members -> case ===")
        member = Member(oauth_id="verify-test-oauth-id", nickname="검증용닉네임")
        session.add(member)
        session.commit()
        session.refresh(member)

        case = Case(member_id=member.id, business_type="음식점")
        session.add(case)
        session.commit()
        session.refresh(case)

        fetched_case = session.exec(select(Case).where(Case.member_id == member.id)).first()
        assert fetched_case is not None and fetched_case.id == case.id, "case.member_id FK 조회 실패"
        print(f"  OK: member.id={member.id} -> case.id={fetched_case.id} (member_id={fetched_case.member_id})")

        print("=== 2. case -> case_history ===")
        history1 = CaseHistory(case_id=case.id, raw_input="검증용 발화 1", source="USER_INPUT")
        session.add(history1)
        session.commit()
        session.refresh(history1)

        fetched_histories = session.exec(select(CaseHistory).where(CaseHistory.case_id == case.id)).all()
        assert len(fetched_histories) == 1 and fetched_histories[0].id == history1.id, "case_history.case_id FK 조회 실패"
        print(f"  OK: case.id={case.id} -> case_history 개수={len(fetched_histories)}")

        # SQLModel Relationship(back_populates)도 실제로 탐색되는지 확인
        session.refresh(case)
        assert any(h.id == history1.id for h in case.histories), "Case.histories relationship 탐색 실패"
        print(f"  OK: case.histories relationship으로도 조회됨 (개수={len(case.histories)})")

        print("=== 3. case_history <-> blocker (순환 참조) ===")
        # blocker가 먼저 case_history를 참조해야 하므로, history1을 만든 뒤 blocker를 만든다.
        blocker = Blocker(
            case_id=case.id,
            created_from_case_log_id=history1.id,
            description="검증용 blocker",
            status="ACTIVE",
        )
        session.add(blocker)
        session.commit()
        session.refresh(blocker)

        # 그 다음 case_history가 이 blocker를 priority_blocker_id로 참조하게 해서 순환을 완성
        history2 = CaseHistory(
            case_id=case.id,
            raw_input="검증용 발화 2 (blocker 확인 질문)",
            source="USER_INPUT",
            priority_blocker_id=blocker.id,
        )
        session.add(history2)
        session.commit()
        session.refresh(history2)

        fetched_blocker = session.exec(select(Blocker).where(Blocker.id == blocker.id)).first()
        assert fetched_blocker.created_from_case_log_id == history1.id, "blocker.created_from_case_log_id FK 불일치"

        fetched_history2 = session.exec(select(CaseHistory).where(CaseHistory.id == history2.id)).first()
        assert fetched_history2.priority_blocker_id == blocker.id, "case_history.priority_blocker_id FK 불일치"
        print(f"  OK: blocker.id={blocker.id} <-> case_history 양방향 순환 참조 정상 (history1={history1.id}, history2={history2.id})")

        print("=== 4. case_history -> case_field_change ===")
        field_change = CaseFieldChange(
            case_history_id=history2.id,
            field_name="demolition_required",
            previous_value="UNKNOWN",
            new_value="REQUIRED",
        )
        session.add(field_change)
        session.commit()
        session.refresh(field_change)

        fetched_changes = session.exec(
            select(CaseFieldChange).where(CaseFieldChange.case_history_id == history2.id)
        ).all()
        assert len(fetched_changes) == 1 and fetched_changes[0].new_value == "REQUIRED", "case_field_change FK 조회 실패"
        print(f"  OK: case_history.id={history2.id} -> case_field_change 개수={len(fetched_changes)}")

        print("\n모든 핵심 관계 검증 통과. 테스트 데이터를 정리합니다...")

        # 생성 역순으로 삭제 (FK 제약 위반 방지)
        session.delete(field_change)
        session.delete(history2)
        session.delete(blocker)
        session.delete(history1)
        session.delete(case)
        session.delete(member)
        session.commit()
        print("테스트 데이터 정리 완료.")


if __name__ == "__main__":
    verify_relations()
