import os

import mysql.connector
from fastapi import FastAPI, HTTPException, Depends
from auth import build_auth_router
from photos import build_photo_router
from albums import build_album_router
from users import build_user_router
from admin import build_admin_router

app = FastAPI(
    title="LocalLens API",
    description="Local photo storage and management API",
    version="0.4.1",
)

def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "db"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "locallens"),
        password=os.environ["DB_PASSWORD"],
        database=os.getenv("DB_NAME", "locallens"),
        connection_timeout=5,
    )

auth_router, get_current_user, require_admin = (
    build_auth_router(get_connection)
)
app.include_router(
    build_user_router(
        get_connection,
        get_current_user
    )
)

app.include_router(
    build_admin_router(
        get_connection,
        require_admin
    )
)
app.include_router(auth_router)
app.include_router(
    build_photo_router(get_connection, get_current_user)
)

app.include_router(
    build_album_router(get_connection, get_current_user)
)



@app.get("/api/health")
def health():
    return {"status": "ok", "application": "LocalLens API"}


@app.get("/api/status")
def status(user=Depends(require_admin)):
    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT 1")
        cursor.fetchone()

        cursor.execute("SELECT COUNT(*) FROM photos")
        photo_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM albums")
        album_count = cursor.fetchone()[0]

        cursor.close()
        connection.close()

        return {
            "application": "LocalLens",
            "api": "connected",
            "database": "connected",
            "photos": photo_count,
            "albums": album_count,
        }

    except mysql.connector.Error as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database connection or query failed: {exc}",
        ) from exc
