-- 시연 계정을 가입 전으로 되돌린다. 그 회원의 Case와 Case에 딸린 기록을 모두 지운다.
-- members 행은 남겨서 같은 카카오 계정으로 로그인하면 진단부터 다시 시작한다.
-- 절차·공식 문서·지원 항목처럼 모든 회원이 같이 쓰는 표는 건드리지 않는다.
--
-- 쓰는 법: 회원 번호를 --init-command로 넘긴다(EC2, docker-compose.prod.yml이 있는 폴더에서). 파일은 고치지 않는다.
--   docker compose -f docker-compose.prod.yml exec -T mysql mysql --defaults-extra-file=/run/secrets/mysql_health_cnf --init-command="SET @member_id = 7" closure_agent < backend/sql/reset_member_case.sql
-- 회원 번호 찾기: SELECT m.id, m.nickname, c.id AS case_id FROM members m LEFT JOIN `case` c ON c.member_id = m.id;
-- 번호를 안 넘기면 @member_id가 비어 있어 아무것도 지우지 않는다.
--
-- 한 트랜잭션이라 중간에 실패하면 아무것도 지워지지 않는다. Case가 없는 회원이면 아무 일도 없다.
-- 올린 서류 파일(document_data 볼륨)은 지우지 않는다. 새 Case는 다른 폴더를 써서 섞이지 않는다.
-- Case를 가리키는 표가 새로 생기면 여기에도 더해야 한다. 빠지면 tests/test_reset_member_case.py가 실패한다.

START TRANSACTION;

SET @case_id = (SELECT id FROM `case` WHERE member_id = @member_id);

-- case_history ↔ blocker가 서로를 가리켜서, 판단 이력이 가리키는 우선 Blocker를 먼저 비운다
UPDATE case_history SET priority_blocker_id = NULL WHERE case_id = @case_id;

DELETE FROM evidence_lineage
 WHERE evidence_id IN (SELECT id FROM evidence WHERE case_id = @case_id)
    OR parent_evidence_id IN (SELECT id FROM evidence WHERE case_id = @case_id);
DELETE FROM case_procedure_step_history
 WHERE case_procedure_step_id IN (SELECT id FROM case_procedure_step WHERE case_id = @case_id);

DELETE FROM evidence WHERE case_id = @case_id;
DELETE FROM decision_record WHERE case_id = @case_id;
DELETE FROM conflict_reference WHERE case_id = @case_id;
DELETE FROM case_field_history WHERE case_id = @case_id;
DELETE FROM case_procedure_step WHERE case_id = @case_id;
DELETE FROM case_checklist WHERE case_id = @case_id;
DELETE FROM case_checklist_history WHERE case_id = @case_id;
DELETE FROM case_document_history WHERE case_id = @case_id;
DELETE FROM support_item_application WHERE case_id = @case_id;
DELETE FROM support_match WHERE case_id = @case_id;
DELETE FROM blocker WHERE case_id = @case_id;
DELETE FROM case_history WHERE case_id = @case_id;
DELETE FROM `case` WHERE id = @case_id;

COMMIT;
