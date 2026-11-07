-- 빈 DB 전용이다. 표를 처음 만들 때만 넣는다. 이미 표가 있으면 "already exists"로 멈추고 아무것도 지우지 않는다.
-- 넣는 법(EC2, docker-compose.prod.yml이 있는 폴더에서):
--   docker compose -f docker-compose.prod.yml exec -T mysql mysql --defaults-extra-file=/run/secrets/mysql_health_cnf closure_agent < backend/sql/001_schema.sql
--
-- 이미 돌고 있는 DB에 칸·값을 더할 때는 이 파일이 아니라 002처럼 고치는 SQL을 따로 만들어 넣는다.
-- CI(tests/test_schema_sql.py)는 모델과 이 파일이 같은지만 본다. 고치는 SQL을 빠뜨렸는지는 보지 않는다(현종님 #217).
--
-- 손으로 고치지 않는다. 모델을 바꾸면 backend에서 python -m scripts.dump_schema_sql 로 다시 뽑는다.

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `blocker` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `case_id` bigint NOT NULL,
  `candidate_id` text,
  `created_from_case_history_id` bigint NOT NULL COMMENT '이 blocker를 생성시킨 판단 로그',
  `resolved_from_case_history_id` bigint DEFAULT NULL COMMENT '이 blocker를 해소시킨 판단 로그, 해소 전까지 None',
  `description` text NOT NULL,
  `blocker_evidence_refs` json DEFAULT NULL,
  `status` enum('ACTIVE','RESOLVED') NOT NULL DEFAULT 'ACTIVE',
  `resolved_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `case_id` (`case_id`),
  KEY `created_from_case_history_id` (`created_from_case_history_id`),
  KEY `resolved_from_case_history_id` (`resolved_from_case_history_id`),
  CONSTRAINT `blocker_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`),
  CONSTRAINT `blocker_ibfk_2` FOREIGN KEY (`created_from_case_history_id`) REFERENCES `case_history` (`id`),
  CONSTRAINT `blocker_ibfk_3` FOREIGN KEY (`resolved_from_case_history_id`) REFERENCES `case_history` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `case` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `member_id` bigint NOT NULL,
  `store_name` varchar(50) DEFAULT NULL,
  `business_type` varchar(50) NOT NULL,
  `franchise_status` tinyint(1) NOT NULL,
  `employee_count` int DEFAULT NULL,
  `has_business_loan` tinyint(1) DEFAULT NULL,
  `has_service_contracts` tinyint(1) DEFAULT NULL,
  `had_employees` tinyint(1) DEFAULT NULL,
  `pension_enrolled` tinyint(1) DEFAULT NULL,
  `health_insurance_enrolled` tinyint(1) DEFAULT NULL,
  `employment_insurance_enrolled` tinyint(1) DEFAULT NULL,
  `industrial_accident_insurance_enrolled` tinyint(1) DEFAULT NULL,
  `case_status` enum('IN_PROGRESS','COMPLETED') NOT NULL DEFAULT 'IN_PROGRESS',
  `lease_status` enum('LEASED_PAID','LEASED_FREE','OWNED') NOT NULL,
  `restoration_clause` enum('EXISTS','NOT_EXISTS','UNKNOWN') NOT NULL DEFAULT 'UNKNOWN',
  `restoration_status` enum('UNKNOWN','NOT_STARTED','IN_PROGRESS','COMPLETED','NOT_REQUIRED') NOT NULL DEFAULT 'UNKNOWN',
  `restoration_scope` enum('UNKNOWN','PARTIAL','FULL','NOT_REQUIRED') NOT NULL DEFAULT 'UNKNOWN',
  `restoration_scope_detail` varchar(1000) DEFAULT NULL,
  `demolition_required` enum('UNKNOWN','REQUIRED','NOT_REQUIRED') NOT NULL DEFAULT 'UNKNOWN',
  `support_approved` tinyint(1) DEFAULT NULL,
  `support_approved_at` datetime DEFAULT NULL,
  `planned_closure_date` date DEFAULT NULL,
  `planned_closure_month` varchar(7) DEFAULT NULL,
  `completed_at` datetime DEFAULT NULL,
  `closure_date` date DEFAULT NULL,
  `closure_reason` enum('BUSINESS_SLUMP','PERSONAL','OTHER') DEFAULT NULL,
  `road_address` varchar(200) DEFAULT NULL,
  `address_detail` varchar(100) DEFAULT NULL,
  `deposit_return_result` enum('FULL','PARTIAL','NONE') DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `member_id` (`member_id`),
  CONSTRAINT `case_ibfk_1` FOREIGN KEY (`member_id`) REFERENCES `members` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `case_checklist` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `case_id` bigint NOT NULL,
  `task_id` varchar(50) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_case_checklist` (`case_id`,`task_id`),
  CONSTRAINT `case_checklist_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `case_checklist_history` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `case_id` bigint NOT NULL,
  `task_id` varchar(50) NOT NULL,
  `completed` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `case_id` (`case_id`),
  CONSTRAINT `case_checklist_history_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `case_document_context` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `case_id` bigint NOT NULL,
  `context` json NOT NULL,
  `judged_context` json DEFAULT NULL,
  PRIMARY KEY (`case_id`),
  CONSTRAINT `case_document_context_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `case_document_history` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `case_id` bigint NOT NULL,
  `action` enum('UPLOADED','CHECKED') NOT NULL,
  `document_kind` varchar(30) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `case_id` (`case_id`),
  CONSTRAINT `case_document_history_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `case_field_history` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `case_id` bigint NOT NULL,
  `case_history_id` bigint DEFAULT NULL,
  `source_evidence_refs` json DEFAULT NULL,
  `canonical_field` varchar(100) NOT NULL,
  `before_value` varchar(1000) DEFAULT NULL,
  `after_value` varchar(1000) DEFAULT NULL,
  `source` varchar(50) NOT NULL,
  `reason` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `case_id` (`case_id`),
  KEY `case_history_id` (`case_history_id`),
  CONSTRAINT `case_field_history_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`),
  CONSTRAINT `case_field_history_ibfk_2` FOREIGN KEY (`case_history_id`) REFERENCES `case_history` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `case_history` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `case_id` bigint NOT NULL,
  `raw_input` text,
  `restoration_answer` json DEFAULT NULL,
  `conflict_snapshot` json DEFAULT NULL,
  `retained_info_result` json DEFAULT NULL,
  `source` enum('USER_INPUT','SYSTEM_BATCH','CASE_CREATED','CONFLICT_DECISION','DOCUMENT_SUBMITTED') NOT NULL,
  `judgment_status` enum('PENDING','DONE','NEEDS_MORE_INFO','CONFLICT','FAILED') NOT NULL,
  `next_action` text,
  `next_action_code` varchar(100) DEFAULT NULL,
  `next_action_reason` text,
  `next_action_questions_to_ask` json DEFAULT NULL,
  `next_action_evidence_refs` json DEFAULT NULL,
  `questions_for_user` json DEFAULT NULL,
  `roadmap_task_ids` json DEFAULT NULL,
  `failure_code` varchar(100) DEFAULT NULL,
  `recovery_action_code` enum('RETRY','RESUBMIT_INPUT','CONTACT_SUPPORT','NONE') DEFAULT NULL,
  `requested_field_paths` json DEFAULT NULL,
  `retryable` tinyint(1) DEFAULT NULL,
  `judged_at` datetime DEFAULT NULL,
  `priority_blocker_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `case_id` (`case_id`),
  KEY `fk_case_history_priority_blocker` (`priority_blocker_id`),
  CONSTRAINT `case_history_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`),
  CONSTRAINT `fk_case_history_priority_blocker` FOREIGN KEY (`priority_blocker_id`) REFERENCES `blocker` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `case_procedure_step` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `case_id` bigint NOT NULL,
  `procedure_step_id` bigint NOT NULL,
  `status` enum('NOT_STARTED','IN_PROGRESS','COMPLETED') NOT NULL DEFAULT 'NOT_STARTED',
  `requirements_confirmed` tinyint(1) NOT NULL DEFAULT '0',
  `submitted` tinyint(1) NOT NULL DEFAULT '0',
  `evidence_refs` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_case_procedure_step` (`case_id`,`procedure_step_id`),
  KEY `procedure_step_id` (`procedure_step_id`),
  CONSTRAINT `case_procedure_step_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`),
  CONSTRAINT `case_procedure_step_ibfk_2` FOREIGN KEY (`procedure_step_id`) REFERENCES `procedure_step` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `case_procedure_step_history` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `case_procedure_step_id` bigint NOT NULL,
  `case_history_id` bigint DEFAULT NULL,
  `previous_status` enum('NOT_STARTED','IN_PROGRESS','COMPLETED') NOT NULL,
  `new_status` enum('NOT_STARTED','IN_PROGRESS','COMPLETED') NOT NULL,
  PRIMARY KEY (`id`),
  KEY `case_procedure_step_id` (`case_procedure_step_id`),
  KEY `case_history_id` (`case_history_id`),
  CONSTRAINT `case_procedure_step_history_ibfk_1` FOREIGN KEY (`case_procedure_step_id`) REFERENCES `case_procedure_step` (`id`),
  CONSTRAINT `case_procedure_step_history_ibfk_2` FOREIGN KEY (`case_history_id`) REFERENCES `case_history` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `conflict_reference` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `conflict_ref` varchar(100) NOT NULL,
  `case_id` bigint NOT NULL,
  `case_history_id` bigint NOT NULL,
  `canonical_field` varchar(100) NOT NULL,
  `committed_value` varchar(1000) DEFAULT NULL,
  `proposed_value` varchar(1000) NOT NULL,
  `conflict_digest` varchar(255) DEFAULT NULL,
  `candidate_payload` json DEFAULT NULL,
  `status` enum('PENDING','CONFIRMED','REJECTED') NOT NULL,
  `decided_at` datetime DEFAULT NULL,
  `resolved_by_case_history_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `conflict_ref` (`conflict_ref`),
  KEY `case_id` (`case_id`),
  KEY `case_history_id` (`case_history_id`),
  KEY `fk_conflict_reference_resolved_by` (`resolved_by_case_history_id`),
  CONSTRAINT `conflict_reference_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`),
  CONSTRAINT `conflict_reference_ibfk_2` FOREIGN KEY (`case_history_id`) REFERENCES `case_history` (`id`),
  CONSTRAINT `fk_conflict_reference_resolved_by` FOREIGN KEY (`resolved_by_case_history_id`) REFERENCES `case_history` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `decision_record` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `case_id` bigint NOT NULL,
  `case_history_id` bigint NOT NULL COMMENT '이 판단을 일으킨 입력 이력',
  `run_id` varchar(100) NOT NULL,
  `snapshot_id` varchar(36) NOT NULL,
  `trace_id` varchar(100) DEFAULT NULL,
  `review_subject_id` varchar(100) NOT NULL,
  `review_attempt` int NOT NULL,
  `subject_digest` varchar(255) DEFAULT NULL,
  `verdict` varchar(50) NOT NULL,
  `decision_type` varchar(50) NOT NULL,
  `summary` text,
  `human_confirmation_required` tinyint(1) NOT NULL,
  `reviewed_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `case_id` (`case_id`),
  KEY `case_history_id` (`case_history_id`),
  CONSTRAINT `decision_record_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`),
  CONSTRAINT `decision_record_ibfk_2` FOREIGN KEY (`case_history_id`) REFERENCES `case_history` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `evidence` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `evidence_id` varchar(100) NOT NULL,
  `case_id` bigint NOT NULL,
  `source_type` enum('USER_INPUT','EXPERT_CONFIRMATION','REVIEWED_WIKI','OFFICIAL_DOCUMENT','OFFICIAL_API','CALCULATION_RESULT','SYSTEM_RECORD') NOT NULL,
  `source_ref` varchar(500) NOT NULL,
  `source_version` varchar(100) DEFAULT NULL,
  `locator` varchar(255) DEFAULT NULL,
  `excerpt` text,
  `official_document_id` bigint DEFAULT NULL,
  `published_at` datetime DEFAULT NULL,
  `retrieved_at` datetime NOT NULL,
  `freshness_status` enum('CURRENT','STALE','UNKNOWN') NOT NULL,
  `content_hash` varchar(64) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `evidence_id` (`evidence_id`),
  KEY `case_id` (`case_id`),
  KEY `official_document_id` (`official_document_id`),
  CONSTRAINT `evidence_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`),
  CONSTRAINT `evidence_ibfk_2` FOREIGN KEY (`official_document_id`) REFERENCES `official_document` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `evidence_lineage` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `evidence_id` bigint NOT NULL,
  `parent_evidence_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_evidence_lineage` (`evidence_id`,`parent_evidence_id`),
  KEY `parent_evidence_id` (`parent_evidence_id`),
  CONSTRAINT `evidence_lineage_ibfk_1` FOREIGN KEY (`evidence_id`) REFERENCES `evidence` (`id`),
  CONSTRAINT `evidence_lineage_ibfk_2` FOREIGN KEY (`parent_evidence_id`) REFERENCES `evidence` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `members` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `oauth_id` varchar(255) NOT NULL,
  `nickname` varchar(255) NOT NULL,
  `refresh_token` varchar(512) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `oauth_id` (`oauth_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `official_document` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `source_ref` varchar(500) NOT NULL,
  `source_version` varchar(100) NOT NULL,
  `excerpt` text NOT NULL,
  `content_hash` varchar(64) NOT NULL,
  `published_at` datetime DEFAULT NULL,
  `retrieved_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_official_document_source_version` (`source_ref`,`source_version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `procedure_step` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `step_code` varchar(100) NOT NULL,
  `step_name` varchar(255) NOT NULL,
  `utterance_aliases` json DEFAULT NULL,
  `registry_version` varchar(50) NOT NULL,
  `deprecated_at` datetime DEFAULT NULL,
  `replaced_by_procedure_step_id` bigint DEFAULT NULL,
  `responsible_agency` varchar(255) DEFAULT NULL,
  `deadline_rule` varchar(255) DEFAULT NULL,
  `required_documents` json DEFAULT NULL,
  `requires_professional` tinyint(1) NOT NULL,
  `professional_type` varchar(100) DEFAULT NULL,
  `caution_note` text,
  `applicable_business_type` enum('ALL','CAFE') NOT NULL DEFAULT 'ALL',
  PRIMARY KEY (`id`),
  UNIQUE KEY `step_code` (`step_code`),
  KEY `replaced_by_procedure_step_id` (`replaced_by_procedure_step_id`),
  CONSTRAINT `procedure_step_ibfk_1` FOREIGN KEY (`replaced_by_procedure_step_id`) REFERENCES `procedure_step` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `step_dependency` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `procedure_step_id` bigint NOT NULL,
  `prerequisite_procedure_step_id` bigint NOT NULL,
  `dependency_type` varchar(50) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `procedure_step_id` (`procedure_step_id`),
  KEY `prerequisite_procedure_step_id` (`prerequisite_procedure_step_id`),
  CONSTRAINT `step_dependency_ibfk_1` FOREIGN KEY (`procedure_step_id`) REFERENCES `procedure_step` (`id`),
  CONSTRAINT `step_dependency_ibfk_2` FOREIGN KEY (`prerequisite_procedure_step_id`) REFERENCES `procedure_step` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `step_eligibility` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `procedure_step_id` bigint NOT NULL,
  `condition_key` varchar(100) NOT NULL,
  `condition_value` varchar(255) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `procedure_step_id` (`procedure_step_id`),
  CONSTRAINT `step_eligibility_ibfk_1` FOREIGN KEY (`procedure_step_id`) REFERENCES `procedure_step` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `support_item` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `uuid` varchar(36) NOT NULL,
  `external_notice_id` varchar(100) DEFAULT NULL,
  `catalog_version` varchar(50) DEFAULT NULL,
  `program_name` varchar(255) NOT NULL,
  `application_start_date` date DEFAULT NULL,
  `application_end_date` date DEFAULT NULL,
  `source_file_location` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uuid` (`uuid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `support_item_application` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `case_id` bigint NOT NULL,
  `support_item_id` bigint NOT NULL,
  `application_status` enum('NOT_STARTED','APPLIED','SUPPLEMENT_REQUIRED','RESUBMITTED','APPROVED','REJECTED') NOT NULL DEFAULT 'NOT_STARTED',
  `applied_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `case_id` (`case_id`),
  KEY `support_item_id` (`support_item_id`),
  CONSTRAINT `support_item_application_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`),
  CONSTRAINT `support_item_application_ibfk_2` FOREIGN KEY (`support_item_id`) REFERENCES `support_item` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `support_match` (
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` bigint NOT NULL AUTO_INCREMENT,
  `case_id` bigint NOT NULL,
  `support_item_id` bigint NOT NULL,
  `match_status` enum('POSSIBLY_RELEVANT','NEEDS_CONFIRMATION','NOT_RELEVANT','STALE','UNVERIFIABLE') NOT NULL,
  `catalog_version` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `case_id` (`case_id`),
  KEY `support_item_id` (`support_item_id`),
  CONSTRAINT `support_match_ibfk_1` FOREIGN KEY (`case_id`) REFERENCES `case` (`id`),
  CONSTRAINT `support_match_ibfk_2` FOREIGN KEY (`support_item_id`) REFERENCES `support_item` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

