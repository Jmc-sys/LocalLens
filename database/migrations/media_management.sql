USE locallens;

ALTER TABLE photos
    ADD COLUMN is_favorite BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN description TEXT DEFAULT NULL,
    ADD COLUMN deleted_at DATETIME DEFAULT NULL,
    ADD COLUMN updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    ADD INDEX idx_photos_user_uploaded (user_id, uploaded_at),
    ADD INDEX idx_photos_user_favorite (user_id, is_favorite),
    ADD INDEX idx_photos_user_deleted (user_id, deleted_at),
    ADD INDEX idx_photos_user_sha256 (user_id, sha256);

ALTER TABLE albums
    ADD COLUMN updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP;
