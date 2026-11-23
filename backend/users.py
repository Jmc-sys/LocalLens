import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from mysql.connector import IntegrityError

from security import hash_password, verify_password
from photos import database
from guard import throttle, audit


class RegistrationRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    display_name: str = Field(default="", max_length=100)
    password: str = Field(min_length=12, max_length=128)


class ProfileUpdate(BaseModel):
    email: EmailStr
    display_name: str = Field(default="", max_length=100)


class PasswordUpdate(BaseModel):
    current_password: str = Field(
        min_length=1, max_length=128
    )
    new_password: str = Field(
        min_length=12, max_length=128
    )


def build_user_router(
    get_connection,
    get_current_user
):
    router = APIRouter(
        prefix="/api/users",
        tags=["Users"]
    )

    @router.get("/registration-status")
    def registration_status():

        with database(get_connection) as (conn, cursor):
            cursor.execute(
                """
                SELECT setting_value
                FROM system_settings
                WHERE setting_key = 'registration_enabled'
                """
            )

            setting = cursor.fetchone()

            return {
                "enabled": bool(
                    setting and
                    setting["setting_value"] == "true"
                )
            }

    @router.post("/register", status_code=201)
    def register(data: RegistrationRequest, request: Request):
        throttle(get_connection, request, "register-ip", 5, 3600)

        username = data.username.strip().lower()
        email = str(data.email).strip().lower()
        display_name = data.display_name.strip()

        if not re.fullmatch(
            r"[a-z0-9_.-]{3,50}", username
        ):
            raise HTTPException(
                400,
                "Username may contain letters, numbers, "
                "periods, underscores and hyphens"
            )

        try:
            with database(get_connection) as (conn, cursor):

                cursor.execute(
                    """
                    SELECT setting_key, setting_value
                    FROM system_settings
                    WHERE setting_key IN (
                        'registration_enabled',
                        'default_storage_quota_bytes'
                    )
                    """
                )

                settings = {
                    row["setting_key"]: row["setting_value"]
                    for row in cursor.fetchall()
                }

                if settings.get(
                    "registration_enabled"
                ) != "true":
                    raise HTTPException(
                        403, "Account registration is disabled"
                    )

                quota = int(
                    settings.get(
                        "default_storage_quota_bytes",
                        "5368709120"
                    )
                )

                secure_hash = hash_password(data.password)

                cursor.execute(
                    """
                    INSERT INTO users (
                        username,
                        email,
                        display_name,
                        password_hash,
                        role,
                        is_active,
                        storage_quota_bytes
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        'user', TRUE, %s
                    )
                    """,
                    (
                        username,
                        email,
                        display_name or username,
                        secure_hash,
                        quota
                    )
                )

                user_id = cursor.lastrowid
                audit(cursor, "account_created", user_id)
                conn.commit()

                return {
                    "status": "created",
                    "id": user_id,
                    "username": username
                }

        except IntegrityError as exc:
            if exc.errno == 1062:
                raise HTTPException(
                    409,
                    "Username or email is already registered"
                ) from exc

            raise

    @router.patch("/me")
    def update_profile(
        data: ProfileUpdate,
        user=Depends(get_current_user)
    ):
        try:
            with database(get_connection) as (conn, cursor):
                cursor.execute(
                    """
                    UPDATE users
                    SET email = %s,
                        display_name = %s
                    WHERE id = %s
                    """,
                    (
                        str(data.email).strip().lower(),
                        data.display_name.strip(),
                        user["id"]
                    )
                )

                conn.commit()

                return {"status": "updated"}

        except IntegrityError as exc:
            if exc.errno == 1062:
                raise HTTPException(
                    409, "Email is already registered"
                ) from exc

            raise

    @router.post("/me/password")
    def change_password(
        data: PasswordUpdate,
        user=Depends(get_current_user)
    ):
        with database(get_connection) as (conn, cursor):

            cursor.execute(
                """
                SELECT password_hash
                FROM users
                WHERE id = %s
                FOR UPDATE
                """,
                (user["id"],)
            )

            account = cursor.fetchone()

            if not account or not verify_password(
                data.current_password,
                account["password_hash"]
            ):
                raise HTTPException(
                    400, "Current password is incorrect"
                )

            if data.current_password == data.new_password:
                raise HTTPException(
                    400, "New password must be different"
                )

            cursor.execute(
                """
                UPDATE users
                SET password_hash = %s
                WHERE id = %s
                """,
                (
                    hash_password(data.new_password),
                    user["id"]
                )
            )

            cursor.execute("UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE user_id=%s AND revoked_at IS NULL", (user["id"],))
            audit(cursor, "password_changed", user["id"])
            conn.commit()

            return {"status": "password_changed"}

    @router.get("/me/storage")
    def storage_usage(user=Depends(get_current_user)):

        with database(get_connection) as (conn, cursor):

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total_photos,
                    COALESCE(SUM(size_bytes + resource_bytes), 0)
                        AS used_bytes,
                    COALESCE(SUM(
                        CASE
                            WHEN deleted_at IS NOT NULL
                            THEN size_bytes + resource_bytes
                            ELSE 0
                        END
                    ), 0) AS trash_bytes,
                    COALESCE(SUM(
                        CASE
                            WHEN deleted_at IS NOT NULL
                            THEN 1
                            ELSE 0
                        END
                    ), 0) AS trash_photos
                FROM photos
                WHERE user_id = %s
                """,
                (user["id"],)
            )

            storage = cursor.fetchone()

            cursor.execute(
                """
                SELECT COUNT(*) AS total_albums
                FROM albums
                WHERE user_id = %s
                """,
                (user["id"],)
            )

            albums = cursor.fetchone()

            return {
                "total_photos": storage["total_photos"],
                "used_bytes": int(storage["used_bytes"]),
                "trash_bytes": int(storage["trash_bytes"]),
                "trash_photos": int(storage["trash_photos"]),
                "total_albums": albums["total_albums"],
                "quota_bytes": user["storage_quota_bytes"]
            }

    return router
