
USE locallens;

CREATE TABLE IF NOT EXISTS system_settings (
    setting_key VARCHAR(100) NOT NULL,
    setting_value TEXT NOT NULL,
    description VARCHAR(255) DEFAULT NULL,

    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (setting_key)

) ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO system_settings (
    setting_key,
    setting_value,
    description
)
VALUES
(
    'registration_enabled',
    'true',
    'Allow new users to register from the login page'
),
(
    'default_storage_quota_bytes',
    '5368709120',
    'Default storage quota for new accounts'
);
