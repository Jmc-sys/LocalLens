-- Run once AFTER the initial ai_discovery.sql migration.
-- This is additive; no photo, original media, or saved identity is changed.
CREATE TABLE IF NOT EXISTS ai_face_reviews (
  face_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  decision VARCHAR(20) NOT NULL DEFAULT 'unknown',
  reviewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ai_face_reviews_owner (user_id, decision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
