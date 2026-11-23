USE locallens;
SET @q = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='photos' AND column_name='media_type')=0, 'ALTER TABLE photos ADD COLUMN media_type ENUM(''photo'',''live_photo'',''video'') NOT NULL DEFAULT ''photo''', 'SELECT 1');
PREPARE s FROM @q; EXECUTE s; DEALLOCATE PREPARE s;
SET @q = IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='photos' AND column_name='resource_bytes')=0, 'ALTER TABLE photos ADD COLUMN resource_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0', 'SELECT 1');
PREPARE s FROM @q; EXECUTE s; DEALLOCATE PREPARE s;
CREATE TABLE IF NOT EXISTS photo_resources (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 photo_id BIGINT UNSIGNED NOT NULL,
 resource_type ENUM('live_video','raw','adjustment','sidecar','video_preview') NOT NULL,
 original_filename VARCHAR(255) NOT NULL, storage_path VARCHAR(1024) NOT NULL,
 mime_type VARCHAR(100) NOT NULL, size_bytes BIGINT UNSIGNED NOT NULL,
 sha256 CHAR(64) NOT NULL, content_identifier VARCHAR(255), duration_ms INT UNSIGNED,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 INDEX idx_resource_photo(photo_id), INDEX idx_resource_sha256(sha256), INDEX idx_content_identifier(content_identifier),
 CONSTRAINT fk_resource_photo FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
UPDATE photos p SET resource_bytes=(SELECT COALESCE(SUM(r.size_bytes),0) FROM photo_resources r WHERE r.photo_id=p.id);
