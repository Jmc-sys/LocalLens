-- Apply exactly once against LocalLens MySQL 8 after a full database backup.
-- Shared albums REFER to original media; they never duplicate media storage.
CREATE TABLE shared_albums (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    description VARCHAR(500) NOT NULL DEFAULT '',
    created_by BIGINT UNSIGNED NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_shared_album_creator FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE shared_album_members (
    album_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (album_id, user_id),
    KEY idx_shared_member_user (user_id, album_id),
    CONSTRAINT fk_shared_member_album FOREIGN KEY (album_id)
        REFERENCES shared_albums(id) ON DELETE CASCADE,
    CONSTRAINT fk_shared_member_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE shared_album_items (
    album_id BIGINT UNSIGNED NOT NULL,
    photo_id BIGINT UNSIGNED NOT NULL,
    added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (album_id, photo_id),
    KEY idx_shared_item_photo (photo_id, album_id),
    CONSTRAINT fk_shared_item_album FOREIGN KEY (album_id)
        REFERENCES shared_albums(id) ON DELETE CASCADE,
    CONSTRAINT fk_shared_item_photo FOREIGN KEY (photo_id)
        REFERENCES photos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
