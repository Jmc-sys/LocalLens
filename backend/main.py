import os

import mysql.connector
from fastapi import FastAPI, HTTPException, Depends
from auth import build_auth_router
from photos import build_photo_router
from ai_discovery import build_ai_router
from duplicate_preflight import build_duplicate_preflight_router
from shared_albums import build_shared_album_router
from videos import build_video_router
from universal_media import build_universal_media_router
from trash_management import build_trash_router
from live_photos import build_live_router
from albums import build_album_router
from users import build_user_router
from admin import build_admin_router

app = FastAPI(
    title="LocalLens API",
    description="Local photo storage and management API",
    version="0.6.5",
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
app.include_router(build_duplicate_preflight_router(get_connection, get_current_user))
app.include_router(build_shared_album_router(get_connection, get_current_user))
app.include_router(build_video_router(get_connection, get_current_user))
app.include_router(build_universal_media_router(get_connection, get_current_user))
app.include_router(build_trash_router(get_connection, get_current_user))
app.include_router(build_live_router(get_connection, get_current_user))
app.include_router(
    build_photo_router(get_connection, get_current_user)
)

app.include_router(
    build_album_router(get_connection, get_current_user)
)



app.include_router(build_ai_router(get_connection, get_current_user))


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

# LocalLens v0.6: per-user automation and server-side upload protection.
from ai_automation import build_auto_router, AiActivityMiddleware
app.include_router(build_auto_router(get_connection, get_current_user))
app.add_middleware(AiActivityMiddleware, get_connection=get_connection)

# LocalLens v0.6.2: private per-photo corrections to Smart Library suggestions.
from ai_tag_feedback import build_tag_feedback_router
app.include_router(build_tag_feedback_router(get_connection, get_current_user))

# LocalLens v0.6.5: search filenames, corrected tags, learned people, and pets.
from ai_unified_search import build_unified_search_router
from ai_face_review_groups import build_face_group_router
app.include_router(build_unified_search_router(get_connection, get_current_user))
app.include_router(build_face_group_router(get_connection, get_current_user))

# LocalLens v0.6.13: match saved face embeddings without restarting the scanner.
from ai_match_learned import build_match_learned_router
app.include_router(build_match_learned_router(get_connection, get_current_user))

# LocalLens v0.6.15: read-only, authenticated manual-identity statistics.
from ai_manual_identity_stats import build_manual_identity_stats_router
app.include_router(build_manual_identity_stats_router(get_connection, get_current_user))

# LocalLens 0.6.20: authenticated bulk original media downloads.
from bulk_originals import build_bulk_originals_router
app.include_router(build_bulk_originals_router(get_connection, get_current_user))
