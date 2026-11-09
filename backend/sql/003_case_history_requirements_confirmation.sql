-- [준비했어요 / 아직 안 했어요] 버튼(준비 확인 할 일의 결과 입력) 전에 만든 DB에 넣는다.
-- case_history.requirements_confirmation이 없으면 버튼 답을 저장하지 못해 결과 제출이 실패한다. 001_schema.sql로 만든 DB에는 이미 있다.
-- 비어 있어도 되는 칸을 restoration_answer 뒤(001과 같은 자리)에 더할 뿐이라 기존 행은 그대로이고 값은 NULL이다.
-- 같은 DB에 두 번 넣으면 "Duplicate column name"으로 멈추고 아무것도 바꾸지 않는다.
-- 넣는 법(EC2, docker-compose.prod.yml이 있는 폴더에서):
--   docker compose -f docker-compose.prod.yml exec -T mysql mysql --defaults-extra-file=/run/secrets/mysql_health_cnf closure_agent < backend/sql/003_case_history_requirements_confirmation.sql

ALTER TABLE `case_history`
  ADD COLUMN `requirements_confirmation` json DEFAULT NULL AFTER `restoration_answer`;
