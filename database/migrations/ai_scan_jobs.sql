-- LocalLens AI scan status tracking, additive only. Safe to apply again.
-- Never contains image, face, or user identifying information beyond optional scope_user_id.
CREATE TABLE IF NOT EXISTS ai_scan_jobs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  scope_user_id BIGINT UNSIGNED NULL,
  state ENUM('starting','running','completed','failed') NOT NULL DEFAULT 'starting',
  batch_total INT UNSIGNED NOT NULL DEFAULT 0,
  batch_processed INT UNSIGNED NOT NULL DEFAULT 0,
  batch_success INT UNSIGNED NOT NULL DEFAULT 0,
  error_message VARCHAR(500) NULL,
  started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  heartbeat_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME NULL,
  KEY ai_scan_jobs_scope (scope_user_id,id),
  KEY ai_scan_jobs_state (state,heartbeat_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
