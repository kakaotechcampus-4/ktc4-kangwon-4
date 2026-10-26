# 지원사업 자료형

지원사업 조회·추천은 현재 카페 MVP 실행 범위에서 제외한다.
서비스에서 호출하지 않던 Support 실행기와 Wiki 조회 인터페이스는 제거했다.

BE가 사용하는 `ReviewedSupportCatalog`와 지원사업 결과·변경 후보 자료형은 유지한다.
`run_case_planning`의 `support_catalog` 인자도 기존 BE 호출 호환을 위해 남기지만,
현재 절차 판단에 사용하지 않는다.

자료형 기준: [support_agent/models.py](../../backend/app/agent/support_agent/models.py),
[schemas.py](../../backend/app/agent/schemas.py).
