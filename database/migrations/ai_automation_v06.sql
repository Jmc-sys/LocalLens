-- LocalLens v0.6.0: additive metadata. Back up MySQL before applying.
-- No original media, ai_faces names, tags, or photo rows are deleted.
CREATE TABLE IF NOT EXISTS ai_index_control (
  user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  auto_enabled TINYINT(1) NOT NULL DEFAULT 0,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ai_index_activity (
  id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
  last_browse_at DATETIME(6) NULL,
  last_upload_at DATETIME(6) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO ai_index_activity(id) VALUES (1);

CREATE TABLE IF NOT EXISTS ai_upload_leases (
  request_id CHAR(36) NOT NULL PRIMARY KEY,
  heartbeat_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ai_upload_lease_heartbeat(heartbeat_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ai_index_failures (
  photo_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  attempts INT UNSIGNED NOT NULL DEFAULT 0,
  last_error VARCHAR(500) NULL,
  retry_after DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ai_fail_retry(user_id,retry_after)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ai_face_model_health (
  id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
  state ENUM('not_tested','ready','failed') NOT NULL DEFAULT 'not_tested',
  detail VARCHAR(300) NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO ai_face_model_health(id,state) VALUES (1,'not_tested');

CREATE TABLE IF NOT EXISTS ai_pet_labels (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  photo_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  display_name VARCHAR(100) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY ai_pet_unique(user_id,photo_id,display_name),
  KEY ai_pet_photo(user_id,photo_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Existing explicitly named faces are treated as confirmed references.
-- Automatically applied labels never become training references automatically.
SET @add_assignment_sql = IF(
  EXISTS(SELECT 1 FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ai_faces'
           AND COLUMN_NAME='assignment_source'),
  'SELECT 1',
  'ALTER TABLE ai_faces ADD COLUMN assignment_source VARCHAR(20) NOT NULL DEFAULT ''confirmed'''
);
PREPARE ll_stmt FROM @add_assignment_sql;
EXECUTE ll_stmt;
DEALLOCATE PREPARE ll_stmt;

CREATE TABLE IF NOT EXISTS ai_scheduler_heartbeat (
  id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
  last_seen_at DATETIME(6) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO ai_scheduler_heartbeat(id) VALUES (1);

-- Pause is a terminal state for the current partial batch; unprocessed photos
-- are retained in the pending queue for the next idle window.
ALTER TABLE ai_scan_jobs MODIFY COLUMN state
  ENUM('starting','running','completed','failed','paused') NOT NULL DEFAULT 'starting';
