-- v0.6.20 ADDITIVE schema only: does not alter any existing rows or AI tags.
CREATE TABLE IF NOT EXISTS ai_photo_locations (
  photo_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  status VARCHAR(24) NOT NULL,
  city VARCHAR(128) NULL,
  region VARCHAR(128) NULL,
  country VARCHAR(128) NULL,
  indexed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY loc_owner_status (user_id,status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ai_location_tags (
  photo_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  tag VARCHAR(80) NOT NULL,
  PRIMARY KEY (photo_id,tag),
  KEY loc_tag_owner (user_id,tag)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS media_bulk_download_tokens (
  token_digest CHAR(64) NOT NULL PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  photo_ids JSON NOT NULL,
  expires_at DATETIME(6) NOT NULL,
  used_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY bulk_token_expires (expires_at),
  KEY bulk_token_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
