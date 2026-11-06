-- #173(서류 판단) 전에 만든 DB에 넣는다. case_history.source에 DOCUMENT_SUBMITTED가 없으면
-- 서류를 올려 판단을 부를 때 이력을 저장하지 못한다. 001_schema.sql로 만든 DB에는 이미 있다.
-- 이미 들어 있는 DB에 다시 넣어도 같은 정의로 다시 지정할 뿐이라 결과가 같다.
-- 값을 맨 끝에 더하는 것이라 MySQL 8은 표를 다시 쓰지 않고 정의만 바꾼다(기존 행은 그대로).

ALTER TABLE `case_history`
  MODIFY COLUMN `source` enum('USER_INPUT','SYSTEM_BATCH','CASE_CREATED','CONFLICT_DECISION','DOCUMENT_SUBMITTED') NOT NULL;
