USE locallens;

ALTER TABLE photos
    ADD COLUMN user_id BIGINT UNSIGNED DEFAULT NULL,
    ADD INDEX idx_photos_user_id (user_id),
    ADD CONSTRAINT fk_photos_user
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE RESTRICT;

ALTER TABLE albums
    ADD COLUMN user_id BIGINT UNSIGNED DEFAULT NULL,
    ADD INDEX idx_albums_user_id (user_id),
    ADD CONSTRAINT fk_albums_user
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE RESTRICT;
