-- LocalLens v0.6.2: per-photo review of AI classification tags.
-- Additive; no existing photos, faces, names, tags or index progress are reset.
CREATE TABLE IF NOT EXISTS ai_tag_feedback (
  user_id BIGINT UNSIGNED NOT NULL,
  photo_id BIGINT UNSIGNED NOT NULL,
  tag VARCHAR(80) NOT NULL,
  action ENUM('add','reject') NOT NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (photo_id, tag),
  KEY ai_tag_feedback_owner (user_id,photo_id,action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
