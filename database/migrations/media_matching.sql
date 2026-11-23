-- Idempotent schema update; no numeric migration prefix.
-- Apply after taking a full DB backup.
USE locallens;
SET @has_column = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'photos'
    AND COLUMN_NAME = 'content_identifier'
);
SET @ddl = IF(@has_column = 0,
  'ALTER TABLE photos ADD COLUMN content_identifier VARCHAR(255) NULL',
  'SELECT ''content_identifier already exists''');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_index = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'photos'
    AND INDEX_NAME = 'idx_photos_user_content_identifier'
);
SET @ddl = IF(@has_index = 0,
  'CREATE INDEX idx_photos_user_content_identifier ON photos(user_id, content_identifier)',
  'SELECT ''identifier index already exists''');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_column = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'photos'
    AND COLUMN_NAME = 'content_identifier_checked_at'
);
SET @ddl = IF(@has_column = 0,
  'ALTER TABLE photos ADD COLUMN content_identifier_checked_at DATETIME NULL',
  'SELECT ''content_identifier_checked_at already exists''');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
