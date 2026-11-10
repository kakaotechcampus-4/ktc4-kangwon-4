-- 003(준비 확인 버튼)을 넣은 DB에 넣는다. [했어요] 버튼이 준비 확인뿐 아니라 신고 제출·처리 결과 확인·
-- 직접 하는 일까지 받게 되어, 칸 이름을 requirements_confirmation에서 action_done으로 바꾼다.
-- 이름만 바꾸므로 이미 들어 있는 행의 값은 그대로다. 001_schema.sql로 새로 만든 DB에는 이미 action_done이 있어 넣지 않는다.
-- 이미 바꾼 DB에 다시 넣으면 "Unknown column"으로 멈추고 아무것도 바꾸지 않는다.
-- 넣는 법(EC2, docker-compose.prod.yml이 있는 폴더에서):
--   docker compose -f docker-compose.prod.yml exec -T mysql mysql --defaults-extra-file=/run/secrets/mysql_health_cnf closure_agent < backend/sql/004_case_history_action_done.sql

ALTER TABLE `case_history`
  RENAME COLUMN `requirements_confirmation` TO `action_done`;
