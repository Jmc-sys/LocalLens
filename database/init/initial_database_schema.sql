CREATE TABLE IF NOT EXISTS photos (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    original_filename VARCHAR(255) NOT NULL,
    storage_path VARCHAR(1024) NOT NULL,
    thumbnail_path VARCHAR(1024) DEFAULT NULL,
    mime_type VARCHAR(100) DEFAULT NULL,
    size_bytes BIGINT UNSIGNED DEFAULT NULL,
    width INT UNSIGNED DEFAULT NULL,
    height INT UNSIGNED DEFAULT NULL,
    sha256 CHAR(64) DEFAULT NULL,
    captured_at DATETIME DEFAULT NULL,
    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_photos_uploaded_at (uploaded_at),
    INDEX idx_photos_captured_at (captured_at),
    INDEX idx_photos_sha256 (sha256)
);

CREATE TABLE IF NOT EXISTS albums (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    description TEXT DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS album_photos (
    album_id BIGINT UNSIGNED NOT NULL,
    photo_id BIGINT UNSIGNED NOT NULL,
    added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (album_id, photo_id),
    CONSTRAINT fk_album_photos_album
        FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE,
    CONSTRAINT fk_album_photos_photo
        FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE
);
