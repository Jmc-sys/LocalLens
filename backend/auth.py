import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from guard import throttle, audit, database
from security import ACCESS_TOKEN_EXPIRE_MINUTES
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token
)

bearer_scheme = HTTPBearer(auto_error=False)
DUMMY_HASH = hash_password("unused-dummy-password")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


def build_auth_router(get_connection):

    router = APIRouter(
        prefix="/api/auth",
        tags=["Authentication"]
    )

    def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(
            bearer_scheme
        )
    ):
        if credentials is None:
            raise HTTPException(
                status_code=401,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"}
            )

        user_id, session_id = decode_access_token(credentials.credentials)

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute(
                """
                SELECT u.id, u.username, u.email, u.display_name,
                       u.role, u.is_active, u.storage_quota_bytes
                FROM users u JOIN auth_sessions s ON s.user_id = u.id
                WHERE u.id = %s AND s.id = %s
                  AND s.revoked_at IS NULL AND s.expires_at > UTC_TIMESTAMP()
                """,
                (user_id, session_id)
            )

            user = cursor.fetchone()

            if not user or not user["is_active"]:
                raise HTTPException(
                    status_code=401,
                    detail="Account unavailable"
                )

            return user

        finally:
            cursor.close()
            conn.close()

    def require_admin(user=Depends(get_current_user)):

        if user["role"] != "admin":
            raise HTTPException(
                status_code=403,
                detail="Administrator access required"
            )

        return user

    @router.post("/login")
    def login(data: LoginRequest, request: Request):
        throttle(get_connection, request, "login-ip", 30, 900)
        throttle(get_connection, request, "login-account", 8, 900, data.username.strip().lower())

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute(
                """
                SELECT id, username, password_hash, role,
                       is_active
                FROM users
                WHERE username = %s
                LIMIT 1 FOR UPDATE
                """,
                (data.username.strip(),)
            )

            user = cursor.fetchone()

            stored_hash = (
                user["password_hash"] if user
                else DUMMY_HASH
            )

            valid_password = verify_password(
                data.password,
                stored_hash
            )

            if (
                not user
                or not valid_password
                or not user["is_active"]
            ):
                audit(cursor, "login_failed", user["id"] if user else None)
                conn.commit()
                raise HTTPException(
                    status_code=401,
                    detail="Invalid username or password"
                )

            cursor.execute(
                """
                UPDATE users
                SET last_login_at = UTC_TIMESTAMP()
                WHERE id = %s
                """,
                (user["id"],)
            )

            session_id = uuid.uuid4().hex
            cursor.execute("INSERT INTO auth_sessions (id, user_id, expires_at) VALUES (%s, %s, TIMESTAMPADD(MINUTE, %s, UTC_TIMESTAMP()))", (session_id, user["id"], ACCESS_TOKEN_EXPIRE_MINUTES))
            token = create_access_token(user["id"], session_id)
            audit(cursor, "login_success", user["id"])
            conn.commit()

            return {
                "access_token": token,
                "token_type": "bearer",
                "username": user["username"],
                "role": user["role"]
            }

        finally:
            cursor.close()
            conn.close()

    @router.get("/me")
    def current_user(user=Depends(get_current_user)):
        return user

    @router.get("/admin/check")
    def admin_check(user=Depends(require_admin)):
        return {
            "status": "authorized",
            "username": user["username"],
            "role": user["role"]
        }

    @router.post("/logout")
    def logout(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme), user=Depends(get_current_user)):
        _, session_id = decode_access_token(credentials.credentials)
        with database(get_connection) as (conn, cursor):
            cursor.execute("UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE id=%s AND user_id=%s", (session_id, user["id"]))
            audit(cursor, "logout", user["id"])
            conn.commit()
        return {"status": "logged_out"}

    @router.get("/sessions")
    def sessions(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme), user=Depends(get_current_user)):
        _, current_id = decode_access_token(credentials.credentials)
        with database(get_connection) as (conn, cursor):
            cursor.execute("SELECT id, created_at, expires_at FROM auth_sessions WHERE user_id=%s AND revoked_at IS NULL AND expires_at>UTC_TIMESTAMP() ORDER BY created_at DESC", (user["id"],))
            rows = cursor.fetchall()
        return [dict(row, current=row["id"] == current_id) for row in rows]

    @router.delete("/sessions/{session_id}")
    def revoke_session(session_id: str, user=Depends(get_current_user)):
        with database(get_connection) as (conn, cursor):
            cursor.execute("UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE id=%s AND user_id=%s AND revoked_at IS NULL", (session_id, user["id"]))
            if cursor.rowcount == 0:
                raise HTTPException(404, "Session not found")
            audit(cursor, "session_revoked", user["id"])
            conn.commit()
        return {"status": "revoked"}

    return router, get_current_user, require_admin
