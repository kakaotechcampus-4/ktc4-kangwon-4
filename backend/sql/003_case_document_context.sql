-- 서류함(올린 서류 목록·점검 결과)을 파일에서 DB로 옮기기 전에 만든 DB에 넣는다(#242).
-- 예전에는 서류 폴더의 case_documents.json·judged_documents.json에 뒀다.
-- 001_schema.sql로 새로 만든 DB에는 이미 있다.
-- 이미 있는 DB에 다시 넣으면 "already exists"로 멈추고 아무것도 지우지 않는다.
--
-- 서류 원본과 가린 PDF는 그대로 폴더(AGENT_DOCUMENT_DIR)에 있다. 이 표에는 목록만 담는다.
-- 넣는 법(EC2, docker-compose.prod.yml이 있는 폴더에서):
--   docker compose -f docker-compose.prod.yml exec -T mysql mysql --defaults-extra-file=/run/secrets/mysql_health_cnf closure_agent < backend/sql/003_case_document_context.sql

CREATE TABLE `case_document_context` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `case_id` bigint NOT NULL,
  `context` json NOT NULL,
  `judged_context` json DEFAULT NULL,
  PRIMARY KEY (`case_id`),
  CONSTRAINT `case_document_context_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
