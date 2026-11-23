-- LocalLens video library and explicitly approved duplicate copies.
-- Run once on a backed-up database. Requires existing live_photos.sql.
-- A deliberate duplicate has the same genuine SHA256 as the existing file;
-- we therefore cannot keep any unique index on sha256 or (user_id,sha256).
-- Other unique constraints, especially the primary key, remain untouched.

ALTER TABLE photos ADD COLUMN duration_ms BIGINT UNSIGNED NULL;
CREATE INDEX idx_photos_user_media ON photos (user_id, media_type, deleted_at, uploaded_at);

-- Drop only unique indexes consisting of sha256 or user_id+sha256.
SET @drop_sha_unique = (
  SELECT GROUP_CONCAT(CONCAT('DROP INDEX `', REPLACE(INDEX_NAME, '`', '``'), '`') SEPARATOR ', ')
  FROM (
    SELECT INDEX_NAME, MAX(NON_UNIQUE) AS non_unique,
           GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ',') AS columns_in_index
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'photos'
    GROUP BY INDEX_NAME
  ) AS indexes
  WHERE non_unique = 0 AND INDEX_NAME <> 'PRIMARY'
    AND columns_in_index IN ('sha256', 'user_id,sha256', 'sha256,user_id')
);
SET @ddl = IF(@drop_sha_unique IS NULL, 'SELECT 1', CONCAT('ALTER TABLE photos ', @drop_sha_unique));
PREPARE drop_sha_constraint FROM @ddl;
EXECUTE drop_sha_constraint;
DEALLOCATE PREPARE drop_sha_constraint;

-- Keep per-user SHA256 lookup fast, but allow user-approved duplicate records.
SET @sha_lookup_exists = (
  SELECT COUNT(*) FROM (
    SELECT INDEX_NAME,
           GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ',') AS columns_in_index
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'photos'
    GROUP BY INDEX_NAME
  ) AS indexes
  WHERE columns_in_index LIKE 'user_id,sha256%'
);
SET @ddl = IF(@sha_lookup_exists > 0, 'SELECT 1',
              'CREATE INDEX idx_photos_video_user_sha ON photos (user_id, sha256)');
PREPARE ensure_sha_lookup FROM @ddl;
EXECUTE ensure_sha_lookup;
DEALLOCATE PREPARE ensure_sha_lookup;

-- Albums already link to photos.id, so photo and video rows can coexist.
-- Existing trash/quotas already use photos and photo_resources.
