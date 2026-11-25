-- LocalLens AI Discover (private, per-account). Run once after a full database backup.
CREATE TABLE IF NOT EXISTS ai_scans (
  photo_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  tags_done TINYINT(1) NOT NULL DEFAULT 0,
  faces_done TINYINT(1) NOT NULL DEFAULT 0,
  error_message VARCHAR(255) NULL,
  scanned_at DATETIME NULL,
  KEY ai_scans_user (user_id, tags_done, faces_done)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS ai_tags (
  photo_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  tag VARCHAR(80) NOT NULL,
  score FLOAT NOT NULL DEFAULT 0,
  PRIMARY KEY (photo_id, tag),
  KEY ai_tags_lookup (user_id, tag, photo_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS ai_face_settings (
  user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  enabled TINYINT(1) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS ai_people (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  display_name VARCHAR(100) NOT NULL,
  UNIQUE KEY ai_people_name (user_id, display_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS ai_faces (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  photo_id BIGINT UNSIGNED NOT NULL,
  face_index INT UNSIGNED NOT NULL,
  x FLOAT NOT NULL,
  y FLOAT NOT NULL,
  w FLOAT NOT NULL,
  h FLOAT NOT NULL,
  embedding VARBINARY(2048) NOT NULL,
  person_id BIGINT UNSIGNED NULL,
  suggested_person_id BIGINT UNSIGNED NULL,
  similarity FLOAT NULL,
  UNIQUE KEY ai_face_unique (photo_id,face_index),
  KEY ai_face_user (user_id,person_id),
  KEY ai_face_photo (photo_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
