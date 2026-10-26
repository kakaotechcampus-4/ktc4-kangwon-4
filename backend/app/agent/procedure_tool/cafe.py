"""Fixed cafe procedure definitions and official text compared on 2026-10-18.

This module performs no network or database access. Hashes identify fetched HTML
or PDF bytes; excerpts normalize decorative source glyphs only. Automated
comparison supports human review; it does not approve these records for serving.
A team member must read them and record their name and review time before use.
"""

from collections.abc import Mapping
from urllib.parse import urlsplit

from app.agent.action_catalog import PROCEDURE_LABELS
from app.agent.procedure_tool.store import ReviewedProcedureSnapshot
from app.agent.schemas import (
    KnownProcedureStep,
    ProcedureStepRef,
    validate_procedure_registry,
)

CAFE_REGISTRY_VERSION = "cafe-closure/2026-10-18"
# Text-only correction; fetched-body hashes and collection times are unchanged.
CAFE_SOURCE_VERSION = "cafe-official-sources/2026-10-18-text1"

_OFFICIAL_RECORDS = (
    {
        "record_id": "TAX_BUSINESS_CLOSURE",
        "title": "휴·폐업 신고",
        "authority_name": "국세청",
        "canonical_url": "https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7780&mi=2447",
        "excerpt": "휴·폐업 신고(부가가치세법 제8조 및 동법 시행령 제13조)\n"
        "「휴업(폐업)신고서」제출\n"
        "사업자등록을 한 사업자가 휴업 또는 폐업하거나 사업개시일 전에 등록한 자가 사실상 사업을 개시하지 아니하게 되는 때에는 지체없이「휴업(폐업)신고서」에 "
        "사업자등록증을 첨부하여 사업장 관할세무서 또는 가까운 세무서 민원봉사실에 제출하여야 함\n"
        "다만, 사업자가 부가가치세확정신고서에 폐업연월일 및 폐업사유를 기재하고 사업자등록증을 첨부하여 제출한 경우에는 폐업신고서를 제출한 것으로 봄\n"
        "법령에 의해 허가·등록 또는 신고를 하는 사업을 하는 사업자가 폐업신고를 할 경우에는 시·군·구 등의 관할관청에 폐업신고를 한 사실을 확인할 수 있는 서류 "
        "첨부하여야 함\n"
        "홈택스 가입 사업자의 경우 공동인증서로 로그인하여 인터넷 또는 모바일 홈택스에서 휴·폐업 신고 및 휴업 중 재개업 신고가 가능합니다.\n"
        "( 홈택스 - “신청/제출 → 신청업무” 메뉴의 “휴폐업신고”, “(휴업자)재개업신고” )\n"
        "( 모바일 - “국세청 손택스” 앱의 “신청/제출” 또는 “모바일 민원실” )\n"
        "음식업, 이미용 등 공중위생업종, 의료기기업종 등 138개 인,허가 업종(대상업종은 아래 '[별표3]통합 폐업신고로 접수할 수 있는 민원의 종류' 참고)은 아래 "
        "「통합폐업신고서」[별지7호서식]를 작성하여 시군구 또는 세무서 중 한 곳에 제출하면 인허가와 사업자등록 폐업신고를 한 번에 할 수 있습니다.",
        "content_hash": "sha256:5b456edeeb9b3abef4ca7c4ff3592b391c8bfc82d6075cd046b2b3e528a46780",
        "retrieved_at": "2026-10-18T06:23:33.973715+00:00",
        "step_codes": ["FILE_TAX_BUSINESS_CLOSURE"],
        "any_terms": ["사업자", "세무", "국세", "통합"],
    },
    {
        "record_id": "CAFE_CLOSURE_AND_TAX_FOLLOWUP",
        "title": "카페 폐업신고와 후속 세금 안내",
        "authority_name": "찾기쉬운 생활법령정보",
        "canonical_url": "https://www.easylaw.go.kr/CSP/CnpClsMainBtr.laf?ccfNo=5&cciNo=1&cnpClsNo=1&csmSeq=706&popMenu=ov",
        "excerpt": "폐업신고(영업신고 및 사업자등록)\n"
        "폐업신고를 하려는 자는 폐업신고서에 영업허가증 또는 영업신고증을 첨부해 식품의약품안전처장 또는 특별자치시장·특별자치도지사·시장·군수·구청장에게 제출해야 "
        "합니다(\n"
        "「식품위생법」 제37조\n"
        "제3항,\n"
        "「식품위생법 시행규칙」 제44조\n"
        "제1항 및\n"
        "별지 제42호서식\n"
        ").\n"
        "폐업신고를 하려는 사람이 사업자등록의 폐업신고도 함께 하려는 경우에는 음식점 등의 폐업신고서에 사업자등록 폐업신고서를 함께 제출해야 합니다(\n"
        "「식품위생법 시행규칙」 제44조\n"
        "제2항 전단).\n"
        "폐업신고서를 제출받은 식품의약품안전처장 또는 특별자치시장·특별자치도지사·시장·군수·구청장은 즉시 관할 세무서장에게 송부(정보통신망을 이용한 송부 포함)해야 "
        "합니다(\n"
        "「식품위생법」 제37조\n"
        "제3항 및\n"
        "「식품위생법 시행규칙」 제44조\n"
        "제2항 후단).\n"
        "이와 반대로 관할 세무서장에게 음식점 등의 폐업신고서와 사업자등록 폐업신고서를 함께 제출한 경우에는 관할 세무서장이 신고서를 즉시 식품의약품안전처장 또는 "
        "특별자치도지사·시장·군수·구청장에게 송부하므로, 다시 폐업신고서를 제출하지 않아도 됩니다(\n"
        "「부가가치세법 시행령」 제13조\n"
        "제5항 및\n"
        "「식품위생법 시행규칙」 제44조\n"
        "제3항).\n"
        "※ 폐업신고는 업종별로 면허·허가·신고·등록절차에 따라 달라지니 등록 기관에서 확인하시기 바랍니다.\n"
        "※ 폐업절차 및 신청서류에 대한 자세한 사항은 <\n"
        "국세청 사이트 – 사업자등록안내 휴·폐업\n"
        ">에서 확인하실 수 있습니다.\n"
        "부가가치세의 확정신고\n"
        "사업자는 폐업일이 속하는 과세기간의 개시일부터 폐업일까지의 과세표준과 납부세액을 폐업일이 속한 달의 다음 달 25일 이내에 납세지 관할 세무서장에게 신고해야 "
        "합니다(\n"
        "「부가가치세법」 제5조\n"
        "제3항 및\n"
        "제49조\n"
        "제1항 본문).\n"
        "부가가치세의 납부\n"
        "사업자는 그 과세기간에 대한 납부세액을 부가가치세 확정신고서와 함께 각 납세지 관할 세무서장에게 납부하거나\n"
        "「국세징수법」\n"
        "에 따른 납부서를 작성하여 한국은행 또는 체신관서에 납부해야 합니다(\n"
        "「부가가치세법」 제49조\n"
        "제2항).\n"
        "※ 종합소득세는 폐업 후 종합소득세 신고기간인 5월에 신고 후 납부를 하면 됩니다.\n"
        "※ 종합소득세 신고 및 납부에 대한 자세한 사항은 이 콘텐츠의 <\n"
        "세금의 납부\n"
        ">에서 확인하실 수 있습니다.",
        "content_hash": "sha256:3864664b0c2e4f512d9791e2342b9c05d7b91866cfa230d0d142f693c278a7d7",
        "retrieved_at": "2026-10-18T06:23:34.288145+00:00",
        "step_codes": ["FILE_FOOD_SERVICE_CLOSURE", "FILE_TAX_BUSINESS_CLOSURE"],
        "any_terms": ["식품", "영업", "카페", "세무", "통합"],
    },
    {
        "record_id": "LEASE_RESTORATION_AND_RETURN",
        "title": "임차상가건물의 반환의무 및 원상회복의무",
        "authority_name": "찾기쉬운 생활법령정보",
        "canonical_url": "https://www.easylaw.go.kr/CSP/CnpClsMain.laf?ccfNo=3&cciNo=2&cnpClsNo=2&csmSeq=627&popMenu=ov",
        "excerpt": "임차상가건물의 반환의무 및 원상회복의무\n"
        "임차인은 임대차계약이 종료하면 임대인에게 그 상가건물을 반환해야 합니다. 이 경우 임차상가건물을 원래의 상태로 회복하여 반환해야 합니다(\n"
        "「민법」 제654조\n"
        "에 따른 제615조의 준용).\n"
        "임차인의 상가건물 반환의무 및 원상회복의무가 이행불능이 된 경우 그 이행불능으로 인한 손해배상책임을 면하려면 그 이행불능이 임차인 자신의 귀책사유로 말미암은 "
        "것이 아님을 입증할 책임이 있고, 임차건물이 화재로 훼손된 경우 그 화재의 발생원인이 불명인 경우에도 임차인이 그 책임을 면하려면 그 임차건물의 보존 시 선량한 "
        "관리자의 주의의무를 다하였음을 입증해야 합니다(대법원 2010.4.29. 선고 2009다96984 판결).",
        "content_hash": "sha256:9b5bc5632bf322e099395fede7c6b4a132a6b483726e8afa091d51f3d6811855",
        "retrieved_at": "2026-10-18T06:23:34.476547+00:00",
        "step_codes": [
            "CONFIRM_RESTORATION_SCOPE",
            "PERFORM_RESTORATION",
            "RETURN_PREMISES",
        ],
        "any_terms": ["원상복구", "원상회복", "철거", "반환", "임차"],
    },
    {
        "record_id": "EMPLOYEE_FINAL_SETTLEMENT",
        "title": "퇴직 시 금품청산과 지급기일 합의",
        "authority_name": "고용노동부 1350",
        "canonical_url": "https://1350.moel.go.kr/rtmview.do?id=1000305482&page=2&type=ALL",
        "excerpt": "- 근로기준법 제36조에 따라, 사용자는 근로자가 퇴직한 경우에는 그 지급사유가 발생한 때부터 14일 이내에 임금, 보상금, 그 밖의 모든 금품을 지급하여야 "
        "하나, 특별한 사정이 있을 경우에는 당사자 사이의 합의에 의하여 기일을 연장할 수 있습니다.",
        "content_hash": "sha256:22064dc3c739dad827086cd12f61b41b1639e2e97b4fab713c5bd5336ab55618",
        "retrieved_at": "2026-10-18T06:23:34.648558+00:00",
        "step_codes": ["SETTLE_EMPLOYEE_PAYMENTS"],
        "any_terms": ["직원", "임금", "정산", "퇴직"],
    },
    {
        "record_id": "EMPLOYEE_RETIREMENT_BENEFITS",
        "title": "퇴직급여 지급 대상과 기한",
        "authority_name": "고용노동부",
        "canonical_url": "https://www.moel.go.kr/news/cardinfo/view.do?bbs_seq=20210601566",
        "excerpt": "1. 퇴직금은 1년 이상 계속 근로한 근로자가 퇴직할 때 지급합니다. 2. 1년 미만인 근로자, 주 15시간 미만인 근로자는 제외됩니다.\n"
        "퇴직금 지급사유가 발생한 날부터 14일 이내에 지급해야 합니다. 기간 내(당사자 간 합의에 의해 연장 가능)에 지급하지 않은 경우, 그 다음 날부터 지급하는 "
        "날까지 지연 일수에 대해 지연 이자 연 20/100를 지급해야 합니다. 또한, 근로자가 고의로 사업에 막대한 지장을 초래하거나 재산상 손해를 끼쳤을 때에도 "
        "지급해야 합니다. 징계해고 등 어떠한 경우라도 퇴직금 지급을 제한하거나 손해배상액을 빼고 지급할 수 없습니다.",
        "content_hash": "sha256:5c145182c64ceba9d20630f7fc9d46a5600772e8e033d969006da19963e32228",
        "retrieved_at": "2026-10-18T06:23:35.023537+00:00",
        "step_codes": ["SETTLE_EMPLOYEE_PAYMENTS"],
        "any_terms": ["직원", "임금", "정산", "퇴직"],
    },
    {
        "record_id": "SOCIAL_INSURANCE_COMMON_CLOSURE_AND_LOSS",
        "title": "2026년 국민연금 실무안내: 4대보험 공통신고와 기관별 처리결과",
        "authority_name": "국민연금공단",
        "canonical_url": "https://www.nps.or.kr/fileDown.do?atchFileId=FL26000086&atchFileSn=1",
        "excerpt": "다. EDI 서비스 내용\n"
        "(1) 4대 사회보험 공통신고 업무\n"
        "국민연금, 건강보험, 고용/산재보험에 동시신고가 가능한 신고업무\n"
        "• 사업장 탈퇴(소멸)신고서(국민연금, 건강보험, 고용보험, 산재보험)\n"
        "사업장\n"
        "• 사업장 내용변경신고서(국민연금, 건강보험, 고용보험, 산재보험)\n"
        "• 사업장가입자 자격취득/상실신고서(국민연금, 건강보험, 고용보험, 산재보험)\n"
        "※ 취득(상실) 취소 공통신고 가능(국민/건강만 해당, 2022.7.1.부터)\n"
        "• 사업장가입자 내용변경신고서(국민연금, 건강보험, 고용보험, 산재보험)\n"
        "사업장가입자\n"
        "※ 성명, 주민등록번호, 특수직종 여부, 취득일(국민/건강만 해당)변경 가능\n"
        "• 고용보험 이직확인서\n"
        "• 기준소득(보수)월액 변경신청서\n"
        "72\n"
        "\n"
        "(2) 증명서 발급\n"
        "사업장 가입내역확인서\n"
        "사업장 가입자명부(전체가입자) 미가입된 내역은 공란으로 표시.\n"
        "사업장(회원)\n"
        "(개별)사업장 가입자명부(300인 미만 발급대상자 선택) 과거의 이력은 보험별로\n"
        "300인 이상 사업장 가입자명부 기관으로 개별 요청\n"
        "개인(비회원) 가입자 가입내역확인서\n"
        "\n"
        "(4) 처리결과 확인\n"
        "① 홈페이지 확인\n"
        "∙ 홈페이지, 지사(방문, 팩스), EDI를 통한 모든 신고･신청의 처리 현황에 대해 조회 가능\n"
        "∙ 홈페이지 초기화면의 [민원처리 현황] 또는 [민원신고] - [민원처리현황 조회]에서 확인\n"
        "∙ 민원신고 처리 상태\n"
        "처리상태 내 용\n"
        "미전송 신고서를 작성(저장) 했지만 처리기관으로 전송되지 않은 상태\n"
        "접수완료 처리기관으로 전송 대기중인 상태(포털사이트 내에서는 접수완료된 상태)\n"
        "접수취소 작성(저장)한 신고서를 취소한 상태\n"
        "전송완료 신고서가 처리기관으로 전송된 상태\n"
        "처리완료 신고서가 처리기관에서 정상적으로 처리된 상태\n"
        "일부오류/\n"
        "신고서의 일부 또는 전체가 오류 처리된 상태\n"
        "처리오류※)\n"
        "※ 해당 신고서의 [상세보기] 단추를 누르면 간단한 오류메시지 사유를 확인할 수 있으며, 자세한 오류내역은\n"
        "[처리자, 지사번호]를 참고하여 처리기관으로 확인하시기 바랍니다.\n"
        "② 알림톡(SMS 등) 확인\n"
        "∙ 홈페이지를 통한 신고･신청 완료 후 알림톡(SMS 등) 수신을 신청한 경우만 확인 가능\n"
        "∙ 최종 처리결과(처리완료/오류)를 처리 기관별로 확인\n"
        "78",
        "content_hash": "sha256:97c9f4c7dd06c3224df23d98c520621ee6d41f3117af169fdbe55c29b39a34d3",
        "retrieved_at": "2026-10-18T06:23:36.100086+00:00",
        "step_codes": [
            "REPORT_WORKPLACE_INSURANCE_CLOSURE",
            "REPORT_EMPLOYEE_INSURANCE_LOSS",
        ],
        "any_terms": ["보험", "직원", "사업장", "상실", "탈퇴"],
    },
    {
        "record_id": "WORKPLACE_INSURANCE_CLOSURE_FORM",
        "title": "국민연금·건강보험 탈퇴 및 고용·산재보험 소멸 신고서",
        "authority_name": "국민건강보험공단",
        "canonical_url": "https://www.nhis.or.kr/static/html/wbdb/f/wbdbf0901.html",
        "excerpt": "■국민건강보험법 시행규칙 [별지 제4호서식]\n"
        "국민연금 [\n"
        "] 사업장 탈퇴신고서\n"
        "건강보험 [\n"
        "] 사업장 탈퇴신고서\n"
        "고용보험 보험관계 [\n"
        "] 소멸 신고서 [\n"
        "] 해지신청서(근로자 종사 사업장)\n"
        "산재보험 보험관계 [\n"
        "] 소멸 신고서 [\n"
        "] 해지신청서(근로자 종사 사업장)\n"
        "※ 유의사항 및 작성방법은 뒤쪽을 참고하시기 바라며, 바탕색이 어두운 난은 신고인(신청인)이 적지 않습니다.\n"
        "접수번호\n"
        "접수일\n"
        "처리기간\n"
        "사업장/ 사업장관리번호/ 명칭-전화번호/ 사업자등록번호-법인등록번호/ 소재지- 우편번호\n"
        "사업장\n"
        "사업장 관리번호\n"
        "명칭\n"
        "전화번호\n"
        "사업자등록번호\n"
        "법인등록번호\n"
        "소재지\n"
        "우편번호\n"
        "(\n"
        ")\n"
        "환급(반환)계좌 사전신고\n"
        "(은행명)\n"
        "(계좌번호)\n"
        "(예금주명)\n"
        "* 보험료 정산 등 환급(반환)금액 발생 시 지급될 계좌입니다.\n"
        "(지급 관련하여 통장사본 등 추가 서류를 요청할 수 있습니다.)\n"
        "보험사무 대행기관(고용-산재)/ 명칭-번호\n"
        "보험사무\n"
        "대행기관\n"
        "(고용ㆍ산재)\n"
        "명칭\n"
        "번호\n"
        "사용자(대표자)/ 성명-주민등록번호(외국인등록번호)/ 주소-우편번호-전화번호(유선/이동전화), 신고(신청)사유/ 공통사항/ 국민연금-건강보험/ 고용-산재보험, "
        "사유 발생일\n"
        "사용자(대표자)\n"
        "성명\n"
        "주민등록번호(외국인등록번호·국내거소신고번호)\n"
        "주소\n"
        "우편번호(\n"
        ")\n"
        "전화번호(유선/이동전화)\n"
        "신고(신청)\n"
        "사유\n"
        "공통사항(중복선택불가)\n"
        "[\n"
        "]폐업\n"
        "[\n"
        "]통폐업\n"
        "[\n"
        "]사업 종료\n"
        "[\n"
        "]기타\n"
        "국민연금ㆍ건강보험\n"
        "[\n"
        "]휴업\n"
        "[\n"
        "]근로자 없음\n"
        "고용ㆍ산재보험\n"
        "[\n"
        "]근로자 없이 1년 경과\n"
        "※ 고용·산재보험의 경우 근로자 없이 1년이 경과되어야 소멸사유에 해당됩니다.\n"
        "사유 발생일\n"
        "탈퇴(소멸) 후 우편물 수령지\n"
        "탈퇴(소멸) 후 우편물 수령지\n"
        "우편번호(\n"
        ")\n"
        "국민연금/ 휴업기간-탈퇴일/ 통폐합시 흡수하는 상업장-명칭-사업장관리번호/소재지\n"
        "국민연금\n"
        "휴업기간\n"
        "탈퇴일\n"
        "통폐합 시\n"
        "흡수하는\n"
        "사업장\n"
        "명칭\n"
        "사업장 관리번호\n"
        "소재지\n"
        "건강보험/ 근로자수-탈퇴일\n"
        "건강보험\n"
        "근로자 수\n"
        "탈퇴일\n"
        "고용/산재 / 산재보험-근로자수-소멸일/ 고용보험-근로자수-소멸일/ 거래은행 계좌 번호 신고서/ 은행명/계좌번호 - 보험료 정산 결과 반환금액이 발생할 경우 "
        "입금될 계좌입니다.\n"
        "고용/산재\n"
        "산재보험\n"
        "근로자 수\n"
        "소멸일\n"
        "고용보험\n"
        "근로자 수\n"
        "소멸일\n"
        "행정정보 공동이용 동의서\n"
        "본인은 이 건 업무처리와 관련하여 담당 직원이 「전자정부법」 제36조제2항에 따른 행정정보의 공동이용을 통하여 뒤쪽의 담당 직원\n"
        "확인사항 중 휴업·폐업 사실 증명원을 확인하는 것에 동의합니다. *동의하지 않는 경우에는 신고인(신청인)이 직접\n"
        "관련 서류를 제출하여야 합니다.\n"
        "신고인(신청인)\n"
        "(서명 또는 인)\n"
        "위와 같이 신고(신청)합니다.\n"
        "년\n"
        "월\n"
        "일\n"
        "신고인ㆍ신청인(가입자)\n"
        "(서명 또는 인)\n"
        "[\n"
        "] 보험사무대행기관(고용ㆍ산재보험만 해당)\n"
        "(서명 또는 인)\n"
        "국민연금공단 이사장/국민건강보험공단 이사장/근로복지공단 ○○지역본부(지사)장 귀하",
        "content_hash": "sha256:d878f667b3a81ae557f76d90468769b9e0dc2938da8e117a80ced02a4d748afb",
        "retrieved_at": "2026-10-18T06:23:36.884203+00:00",
        "step_codes": ["REPORT_WORKPLACE_INSURANCE_CLOSURE"],
        "any_terms": ["보험", "사업장", "탈퇴", "소멸"],
    },
    {
        "record_id": "EMPLOYEE_INSURANCE_LOSS_FORM",
        "title": "사업장가입자 자격상실 신고서와 처리절차",
        "authority_name": "국가법령정보센터",
        "canonical_url": "https://www.law.go.kr/LSW/flDownload.do?bylClsCd=110202&flSeq=160222035&gubun=",
        "excerpt": "■ 고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률 시행규칙 [별지 제22호의6서식] <개정 2023. 6. 30.>\n"
        "[ ]국민연금 사업장가입자 자격상실 신고서 [ ]건강보험 직장가입자 자격상실 신고서\n"
        "[ ]고용보험 근로자 피보험자격상실 신고서 [ ]산재보험 근로자 자격상실 신고서\n"
        "※ 뒤쪽의 유의사항 및 작성방법을 읽고 작성하기 바라며, 색상이 어두운 난은 신고인이 적지 않습니다.\n"
        "※ 같은 사람의 4대 사회보험의 상실 연월일이 다른 경우에는 유의사항을 읽고 작성하기 바랍니다. (앞쪽)\n"
        "접수번호 접수일자 처리기간 3일(고용ㆍ산재보험은 7일)\n"
        "사업장관리번호 명칭 전화번호 팩스번호\n"
        "사업장\n"
        "소재지\n"
        "우편번호( )\n"
        "보험사무대행기관 명칭 번호 하수급인 관리번호(건설공사등의 미승인하수급인에 한함)\n"
        "국민연금 건강보험 [ ]고용보험 [ ]산재보험\n"
        "해당 연도 전년도\n"
        "주민등록번호 상실 연간 보수 총액 상 실 사 유\n"
        "일련 전화번호 보수 총액 보수 총액\n"
        "성명 (외국인등록번호ㆍ 연월일 초일취득ㆍ\n"
        "번호 국내거소신고번호) (휴대전화번호) (YYYY.MM.DD) 상 부 실 호 당월상실자 상 부 실 호 해당 연도 전년도 구분 고용보험 고용보험\n"
        "납부여부 구체적 사유\n"
        "근무 근무 코드\n"
        "보수 총액 보수 총액 산재보험 산재보험\n"
        "개월 수 개월 수\n"
        "희망\n"
        "[ ]\n"
        "희망\n"
        "[ ]\n"
        "희망\n"
        "[ ]\n"
        "희망\n"
        "[ ]\n"
        "위와 같이 피보험자격상실 신고를 합니다.\n"
        "년 월 일\n"
        "신고인(사용자ㆍ대표자) (서명 또는 인) / [ ]보험사무대행기관 (서명 또는 인)\n"
        "국민연금공단 이사장/국민건강보험공단 이사장/근로복지공단 ○○지역본부(지사)장 귀하\n"
        "\n"
        "\n"
        "처리절차\n"
        "신고서 작성 → 접수 및 확인 → 신고서 처리 → 자격상실 및 확인 통지 → 수령\n"
        "신고인 국민연금공단 ㆍ 국민건강보험공단 ㆍ 근로복지공단 신고인",
        "content_hash": "sha256:84664fca25d988a88d9d9b66e67dbe97f2baf5ee8180174e5b2dfea677ad83ef",
        "retrieved_at": "2026-10-18T06:23:37.237545+00:00",
        "step_codes": ["REPORT_EMPLOYEE_INSURANCE_LOSS"],
        "any_terms": ["보험", "직원", "상실", "퇴사"],
    },
)


def build_cafe_reviewed_snapshot() -> ReviewedProcedureSnapshot:
    """Return detached records awaiting human review for this collected version."""
    return ReviewedProcedureSnapshot.model_validate(
        {
            "snapshot_version": CAFE_SOURCE_VERSION,
            "generated_at": max(record["retrieved_at"] for record in _OFFICIAL_RECORDS),
            "locale": "ko-KR",
            "records": [
                {
                    **record,
                    "source_domain": urlsplit(record["canonical_url"]).hostname,
                    "published_at": None,
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "review_valid_days": 90,
                    "required_terms": ["폐업"],
                }
                for record in _OFFICIAL_RECORDS
            ],
        }
    )


def build_cafe_procedure_steps(step_ids: Mapping[str, int]) -> list[KnownProcedureStep]:
    """Bind the eight fixed topics to caller-issued DB IDs without guessing."""
    if set(step_ids) != set(PROCEDURE_LABELS):
        raise ValueError("all eight cafe procedure IDs are required")
    aliases = {
        "CONFIRM_RESTORATION_SCOPE": ["원상복구 범위", "복구 범위 확인"],
        "PERFORM_RESTORATION": ["원상복구 작업", "철거 작업"],
        "RETURN_PREMISES": ["점포 인도", "열쇠 반환"],
        "FILE_TAX_BUSINESS_CLOSURE": ["사업자등록 폐업신고", "세무서 폐업신고"],
        "FILE_FOOD_SERVICE_CLOSURE": ["영업폐업신고", "식품영업 폐업"],
        "SETTLE_EMPLOYEE_PAYMENTS": ["직원 정산", "임금 정산", "퇴직급여 정산"],
        "REPORT_EMPLOYEE_INSURANCE_LOSS": ["직원 자격상실", "퇴사자 보험 상실"],
        "REPORT_WORKPLACE_INSURANCE_CLOSURE": ["사업장 탈퇴", "보험관계 소멸"],
    }
    conditions = {
        "CONFIRM_RESTORATION_SCOPE": [("is_leased", "true")],
        "PERFORM_RESTORATION": [
            ("is_leased", "true"),
            ("restoration_required", "true"),
        ],
        "RETURN_PREMISES": [("is_leased", "true")],
        "SETTLE_EMPLOYEE_PAYMENTS": [("had_employees", "true")],
        "REPORT_EMPLOYEE_INSURANCE_LOSS": [
            ("had_employees", "true"),
            ("has_workplace_insurance", "true"),
        ],
        "REPORT_WORKPLACE_INSURANCE_CLOSURE": [("has_workplace_insurance", "true")],
    }
    steps = [
        KnownProcedureStep(
            procedure_step=ProcedureStepRef(
                procedure_step_id=step_ids[code], step_code=code
            ),
            step_name=label,
            utterance_aliases=aliases[code],
            registry_version=CAFE_REGISTRY_VERSION,
            applicable_business_type="CAFE",
            deprecated_at=None,
            dependencies=(
                [
                    {
                        "prerequisite_procedure_step_id": step_ids[
                            {
                                "PERFORM_RESTORATION": "CONFIRM_RESTORATION_SCOPE",
                                "RETURN_PREMISES": "PERFORM_RESTORATION",
                            }[code]
                        ],
                        "dependency_type": "SEQUENTIAL",
                    }
                ]
                if code in {"PERFORM_RESTORATION", "RETURN_PREMISES"}
                else []
            ),
            eligibility_conditions=[
                {"condition_key": key, "condition_value": value}
                for key, value in conditions.get(code, [])
            ],
        )
        for code, label in PROCEDURE_LABELS.items()
    ]
    validate_procedure_registry(steps)
    return steps
