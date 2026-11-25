from database_schema import read_schema
from family_group import annotate_family_members, set_family_membership
import os
import shutil

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from photos import database
from security import hash_password
from guard import audit


class AccountUpdate(BaseModel):
    is_active: bool | None = None
    storage_quota_bytes: int | None = Field(
        default=None,
        ge=0,
        le=2**63 - 1
    )


class RegistrationSettings(BaseModel):
    enabled: bool
    default_quota_bytes: int = Field(
        ge=0,
        le=2**63 - 1
    )


class PasswordReset(BaseModel):
    password: str = Field(
        min_length=12,
        max_length=128
    )


class FamilyMembershipChange(BaseModel):
    enabled: bool


def build_admin_router(
    get_connection,
    require_admin
):
    router = APIRouter(
        prefix="/api/admin",
        tags=["Administration"],
        dependencies=[Depends(require_admin)]
    )

    @router.get("/users")
    def list_users():

        with database(get_connection) as (conn, cursor):
            cursor.execute(
                """
                SELECT u.id,
                       u.username,
                       u.email,
                       u.display_name,
                       u.role,
                       u.is_active,
                       u.storage_quota_bytes,
                       u.created_at,
                       u.last_login_at,
                       COUNT(p.id) AS photo_count,
                       COALESCE(SUM(p.size_bytes + p.resource_bytes), 0)
                           AS used_bytes
                FROM users u
                LEFT JOIN photos p ON p.user_id = u.id
                GROUP BY u.id
                ORDER BY u.created_at ASC
                """
            )

            return annotate_family_members(get_connection, cursor.fetchall())

    @router.patch("/users/{user_id}")
    def update_user(
        user_id: int,
        data: AccountUpdate,
        admin=Depends(require_admin)
    ):
        with database(get_connection) as (conn, cursor):

            cursor.execute(
                """
                SELECT id, role
                FROM users
                WHERE id = %s
                FOR UPDATE
                """,
                (user_id,)
            )

            target = cursor.fetchone()

            if not target:
                raise HTTPException(404, "User not found")

            updates = data.model_dump(exclude_unset=True)

            if updates.get("is_active") is False:
                if target["role"] == "admin":
                    raise HTTPException(
                        400,
                        "Administrator accounts cannot be "
                        "disabled from this interface"
                    )

            for field, value in updates.items():

                if field == "is_active" and value is None:
                    continue

                cursor.execute(
                    f"""
                    UPDATE users
                    SET {field} = %s
                    WHERE id = %s
                    """,
                    (value, user_id)
                )

            if updates.get("is_active") is False:
                cursor.execute("UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE user_id=%s AND revoked_at IS NULL", (user_id,))
            audit(cursor, "admin_account_updated", admin["id"], user_id)
            conn.commit()

            return {"status": "updated"}

    @router.post("/users/{user_id}/password")
    def reset_password(
        user_id: int,
        data: PasswordReset,
        admin=Depends(require_admin)
    ):
        with database(get_connection) as (conn, cursor):

            cursor.execute(
                """
                SELECT id, role FROM users
                WHERE id = %s FOR UPDATE
                """,
                (user_id,)
            )

            target = cursor.fetchone()

            if not target:
                raise HTTPException(404, "User not found")

            if target["role"] == "admin":
                raise HTTPException(
                    403,
                    "Use account settings to change "
                    "administrator passwords"
                )

            cursor.execute(
                """
                UPDATE users
                SET password_hash = %s
                WHERE id = %s
                """,
                (
                    hash_password(data.password),
                    user_id
                )
            )

            cursor.execute("UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE user_id=%s AND revoked_at IS NULL", (user_id,))
            audit(cursor, "admin_password_reset", admin["id"], user_id)
            conn.commit()

            return {"status": "password_reset"}

    @router.get("/settings")
    def get_settings():

        with database(get_connection) as (conn, cursor):
            cursor.execute(
                """
                SELECT setting_key, setting_value
                FROM system_settings
                """
            )

            settings = {
                row["setting_key"]: row["setting_value"]
                for row in cursor.fetchall()
            }

            return {
                "registration_enabled":
                    settings.get("registration_enabled") == "true",

                "default_quota_bytes": int(
                    settings.get(
                        "default_storage_quota_bytes",
                        "5368709120"
                    )
                )
            }

    @router.patch("/settings")
    def update_settings(data: RegistrationSettings, admin=Depends(require_admin)):

        with database(get_connection) as (conn, cursor):

            for key, value in [
                (
                    "registration_enabled",
                    str(data.enabled).lower()
                ),
                (
                    "default_storage_quota_bytes",
                    str(data.default_quota_bytes)
                )
            ]:
                cursor.execute(
                    """
                    UPDATE system_settings
                    SET setting_value = %s
                    WHERE setting_key = %s
                    """,
                    (value, key)
                )

            if updates.get("is_active") is False:
                cursor.execute("UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE user_id=%s AND revoked_at IS NULL", (user_id,))
            audit(cursor, "admin_account_updated", admin["id"], user_id)
            conn.commit()

            return {"status": "updated"}

    @router.get("/storage")
    def server_storage():

        path = os.getenv("MEDIA_ROOT", "/storage")
        disk = shutil.disk_usage(path)

        with database(get_connection) as (conn, cursor):

            cursor.execute(
                """
                SELECT COUNT(*) AS total_users,
                       SUM(is_active) AS active_users
                FROM users
                """
            )

            users = cursor.fetchone()

            cursor.execute(
                """
                SELECT COUNT(*) AS total_photos,
                    COALESCE(SUM(size_bytes + resource_bytes), 0)
                        AS media_bytes
                FROM photos
                """
            )

            photos = cursor.fetchone()

            cursor.execute(
                "SELECT COUNT(*) AS total_albums FROM albums"
            )

            albums = cursor.fetchone()

            return {
                "disk_total_bytes": disk.total,
                "disk_used_bytes": disk.used,
                "disk_free_bytes": disk.free,
                "total_users": users["total_users"],
                "active_users": int(
                    users["active_users"] or 0
                ),
                "total_photos": photos["total_photos"],
                "media_bytes": int(photos["media_bytes"]),
                "total_albums": albums["total_albums"]
            }

    @router.put("/users/{user_id}/family")
    def update_family_status(user_id: int, data: FamilyMembershipChange,
                             admin=Depends(require_admin)):
        return set_family_membership(get_connection, admin['id'], user_id, data.enabled)

    @router.get("/database/schema")
    def database_structure():
        """Read-only live schema; protected by the parent admin router."""
        return read_schema(get_connection)

    return router
