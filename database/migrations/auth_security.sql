USE locallens;
CREATE TABLE IF NOT EXISTS auth_sessions (
 id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 user_id BIGINT UNSIGNED NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 expires_at DATETIME NOT NULL,
 revoked_at DATETIME NULL,
 INDEX idx_session_user (user_id), INDEX idx_session_expiry (expires_at),
 FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS auth_limits (
 bucket_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 hits INT UNSIGNED NOT NULL,
 reset_at DATETIME NOT NULL,
 INDEX idx_limit_reset (reset_at)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS auth_audit (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 event_type VARCHAR(64) NOT NULL,
 actor_id BIGINT UNSIGNED NULL,
 target_id BIGINT UNSIGNED NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 INDEX idx_audit_created (created_at)
) ENGINE=InnoDB;
