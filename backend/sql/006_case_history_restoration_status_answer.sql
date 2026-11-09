-- 005(서류함 표)까지 넣은 DB에 넣는다. 두 칸을 더한다.
--   restoration_status_answer: 원상복구 진행 상태를 버튼([아직 시작 안 했어요 / 진행 중이에요 / 다 끝냈어요])으로 받은 답
--   judged_version: 판단한 서버의 커밋. 고칠 수 없다고 끝난 실패(NONE)도 서버가 바뀌면 [다시 판단하기]를 보여 준다
-- 둘 다 비어 있어도 되는 칸이라 이미 있는 행은 NULL로 남는다. 001_schema.sql로 새로 만든 DB에는 이미 있어 넣지 않는다.
-- 이미 넣은 DB에 다시 넣으면 "Duplicate column"으로 멈추고 아무것도 바꾸지 않는다.
-- 넣는 법(EC2, docker-compose.prod.yml이 있는 폴더에서):
--   docker compose -f docker-compose.prod.yml exec -T mysql mysql --defaults-extra-file=/run/secrets/mysql_health_cnf closure_agent < backend/sql/006_case_history_restoration_status_answer.sql

ALTER TABLE `case_history`
  ADD COLUMN `restoration_status_answer` json DEFAULT NULL AFTER `action_done`,
  ADD COLUMN `judged_version` varchar(40) DEFAULT NULL AFTER `judged_at`;
