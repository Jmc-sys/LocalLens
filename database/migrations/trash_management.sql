-- Run once, after backing up your database.
USE locallens;

-- 0 = keep trashed photos until the user permanently deletes them.
-- Existing users remain opted out of automatic deletion until they choose a period.
ALTER TABLE users
    ADD COLUMN trash_retention_days SMALLINT UNSIGNED NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS file_delete_queue (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    storage_path VARCHAR(1024) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attempts INT UNSIGNED NOT NULL DEFAULT 0,
    last_error VARCHAR(500) DEFAULT NULL,
    PRIMARY KEY (id),
    INDEX idx_file_delete_queue_user (user_id),
    INDEX idx_file_delete_queue_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
