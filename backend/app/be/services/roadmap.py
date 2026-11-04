"""로드맵을 화면에 낸다. AI의 build_roadmap을 부르고 그 값을 그대로 돌려준다.

판단(run_case_planning)과 다르다. 로드맵은 모델을 부르지 않고, Case와 절차 목록만 보고
계산하는 읽기다. 그래서 여기서는 저장도 하지 않는다.

**돌려받은 값에서 칸을 빼지 않는다.** supported·unsupported_reason까지 그대로 내보낸다 —
프랜차이즈 카페·일반 음식점은 오류가 아니라 supported=false와 안내 문구로 오고, 화면은 그
문구를 그대로 띄운다(시우님 #132).
"""

from fastapi import HTTPException
from sqlmodel import Session

from app.agent.roadmap import CHECKLIST_IDS, Roadmap, RoadmapInput, build_roadmap
from app.be.crud import case as case_crud
from app.be.crud import case_checklist as case_checklist_crud
from app.be.models.case import Case
from app.be.services import agent_runtime as agent_runtime_service
from app.be.services import case_snapshot as case_snapshot_service
from app.be.services import document as document_service

__all__ = ["build_roadmap_input", "get_case_roadmap"]


def build_roadmap_input(session: Session, case: Case) -> RoadmapInput:
    """Case 한 건으로 AI 로드맵 입력을 만든다. 조회와 저장이 같은 입력을 쓰게 따로 뺐다.

    체크 저장(update_case_checklist)은 지금 항목 이름만 보고 "이 가게에 해당하는 항목인지"는
    안 본다. 그 검사를 붙이려면 이 입력이 필요하다고 승준님이 #149에서 짚으셨다.
    """

    return RoadmapInput(
        # 폐업 정리를 마친 Case도 만든다(현석님 #167). 판단과 달리 모델을 안 불러서 막을 이유가 없다.
        case_snapshot=case_snapshot_service.build_roadmap_snapshot(session, case.id),
        known_procedure_steps=agent_runtime_service.build_known_procedure_steps(session),
        # 가입할 때 받은 값이다. 따로 물어볼 것이 없다.
        has_business_loan=case.has_business_loan,
        has_service_contracts=case.has_service_contracts,
        restoration_clause=case.restoration_clause,
        support_approved=case.support_approved,
        # 체크 항목이 AI 쪽에서 바뀌면 DB에 예전 이름이 남는다. 하나라도 섞이면 그 항목만
        # 빠지는 게 아니라 입력 검증이 통째로 실패해서 로드맵이 안 열린다(check_checklist_ids).
        completed_checklists={
            row.task_id
            for row in case_checklist_crud.get_case_checklists_by_case_id(session, case.id)
        }
        & CHECKLIST_IDS,
        # 오늘 할 일과 되묻는 질문은 GET /cases가 맡는다. 화면도 그쪽을 읽는다
        # (frontend/src/adapters/case.ts). 같은 것을 두 API로 나누지 않으려고 비워 둔다.
        # 그래서 로드맵의 next_action·next_task_id·questions_for_user는 늘 비어 나간다(현석님 #178).
        reviewed_plan=None,
        # 서류 점검 결과. 4단계 "AI 서류 점검"은 체크가 아니라 이 값으로만 상태가 정해져서
        # (agent/roadmap.py의 document_check), 안 넘기면 사장님이 점검을 통과해도 계속
        # "시작 전"으로 남는다. 서류를 안 올린 Case는 빈 목록이라 넘겨도 결과가 같다.
        documents=document_service.load_context(document_service.document_directory(), case),
    )


def get_case_roadmap(session: Session, member_id: int) -> Roadmap:
    """로그인한 사장님의 로드맵. AI가 만든 값을 칸 하나 빼지 않고 그대로 돌려준다."""

    case = case_crud.get_case_by_member_id(session, member_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case를 찾을 수 없습니다.")

    return build_roadmap(build_roadmap_input(session, case))
