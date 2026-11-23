"""User-owned permanent deletion and opt-in retention for LocalLens.

Database deletion and file deletion are separated with a durable outbox queue.
A failed unlink never loses the cleanup instruction.
"""
import os
import stat
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "/storage")).resolve()
BATCH_SIZE = 100
SAFE_MEDIA_FOLDERS = {"originals", "thumbnails", "resources", "previews"}


class RetentionSetting(BaseModel):
    # 0 disables automatic deletion; users can pick 1-3650 days.
    days: int = Field(ge=0, le=3650)


def _connection(get_connection):
    conn = get_connection()
    return conn, conn.cursor(dictionary=True)


def _has_resources(cursor):
    cursor.execute(
        "SELECT COUNT(*) AS n FROM information_schema.tables "
        "WHERE table_schema=DATABASE() AND table_name='photo_resources'"
    )
    return cursor.fetchone()["n"] > 0


def _purge_locked(cursor, photo, has_resources):
    """Caller must have selected photo FOR UPDATE and checked it is trashed."""
    paths = [photo["storage_path"], photo["thumbnail_path"]]
    if has_resources:
        cursor.execute(
            "SELECT storage_path FROM photo_resources WHERE photo_id=%s",
            (photo["id"],),
        )
        paths.extend(row["storage_path"] for row in cursor.fetchall())

    # Queue paths in the SAME transaction as the database deletion.
    # Do not delete the files until the transaction is committed.
    for path in set(filter(None, paths)):
        cursor.execute(
            "INSERT INTO file_delete_queue(user_id, storage_path) VALUES(%s,%s)",
            (photo["user_id"], path),
        )
    cursor.execute("DELETE FROM photos WHERE id=%s", (photo["id"],))
    return cursor.rowcount == 1


def purge_one(get_connection, user_id, photo_id):
    conn, cursor = _connection(get_connection)
    try:
        conn.start_transaction()
        cursor.execute(
            "SELECT id,user_id,storage_path,thumbnail_path,deleted_at "
            "FROM photos WHERE id=%s AND user_id=%s FOR UPDATE",
            (photo_id, user_id),
        )
        photo = cursor.fetchone()
        if not photo:
            raise HTTPException(404, "Photo not found")
        if photo["deleted_at"] is None:
            raise HTTPException(409, "Move the photo to trash before permanently deleting it")
        did_delete = _purge_locked(cursor, photo, _has_resources(cursor))
        conn.commit()
        return did_delete
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def purge_user_batch(get_connection, user_id):
    conn, cursor = _connection(get_connection)
    try:
        conn.start_transaction()
        cursor.execute(
            "SELECT id,user_id,storage_path,thumbnail_path,deleted_at "
            "FROM photos WHERE user_id=%s AND deleted_at IS NOT NULL "
            "ORDER BY id LIMIT %s FOR UPDATE",
            (user_id, BATCH_SIZE),
        )
        photos = cursor.fetchall()
        has_resources = _has_resources(cursor) if photos else False
        deleted = sum(_purge_locked(cursor, photo, has_resources) for photo in photos)
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM photos WHERE user_id=%s "
            "AND deleted_at IS NOT NULL LIMIT 1) AS more",
            (user_id,),
        )
        more = bool(cursor.fetchone()["more"])
        conn.commit()
        return {"deleted": deleted, "has_more": more}
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def _file_path_for_user(user_id, recorded_path):
    """Only permit files under this user's known media folders."""
    user_root = (MEDIA_ROOT / "users" / str(user_id)).resolve()
    raw = Path(recorded_path)
    if not raw.is_absolute():
        raise ValueError("Refusing a non-absolute file path")
    # Resolve parents rather than following the final symlink; unlinking the
    # symlink itself cannot delete its target.
    parent = raw.parent.resolve(strict=False)
    if not parent.is_relative_to(user_root):
        raise ValueError("File path is outside the user's storage")
    relative = parent.relative_to(user_root)
    if not relative.parts or relative.parts[0] not in SAFE_MEDIA_FOLDERS:
        raise ValueError("File path is outside an approved media directory")
    if raw.name in ("", ".", ".."):
        raise ValueError("Invalid media filename")
    return parent / raw.name


def drain_file_queue(get_connection, limit=500):
    """Retry filesystem deletions; safe to run repeatedly."""
    conn, cursor = _connection(get_connection)
    removed = failed = 0
    try:
        cursor.execute(
            "SELECT id,user_id,storage_path FROM file_delete_queue "
            "ORDER BY id LIMIT %s", (limit,)
        )
        items = cursor.fetchall()
        for item in items:
            try:
                path = _file_path_for_user(item["user_id"], item["storage_path"])
                try:
                    mode = path.lstat().st_mode
                    if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
                        raise ValueError("Refusing to remove a non-file path")
                    path.unlink()
                except FileNotFoundError:
                    pass  # Already removed, including after a crash/retry.
                cursor.execute("DELETE FROM file_delete_queue WHERE id=%s", (item["id"],))
                conn.commit()
                removed += 1
            except Exception as exc:
                cursor.execute(
                    "UPDATE file_delete_queue SET attempts=attempts+1, "
                    "last_error=%s WHERE id=%s",
                    (str(exc)[:500], item["id"]),
                )
                conn.commit()
                failed += 1
        return {"removed_files": removed, "failed_files": failed}
    finally:
        cursor.close()
        conn.close()


def retention_cleanup(get_connection, max_batches=10):
    """Run from a scheduled job, not as part of request handling."""
    deleted = 0
    for _ in range(max_batches):
        conn, cursor = _connection(get_connection)
        try:
            conn.start_transaction()
            cursor.execute(
                "SELECT p.id,p.user_id,p.storage_path,p.thumbnail_path,p.deleted_at "
                "FROM photos p JOIN users u ON p.user_id=u.id "
                "WHERE p.deleted_at IS NOT NULL AND u.trash_retention_days > 0 "
                "AND p.deleted_at <= DATE_SUB(UTC_TIMESTAMP(), "
                "INTERVAL u.trash_retention_days DAY) "
                "ORDER BY p.deleted_at, p.id LIMIT %s FOR UPDATE",
                (BATCH_SIZE,),
            )
            photos = cursor.fetchall()
            has_resources = _has_resources(cursor) if photos else False
            deleted += sum(_purge_locked(cursor, photo, has_resources) for photo in photos)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()
        if len(photos) < BATCH_SIZE:
            break
    return deleted


def build_trash_router(get_connection, get_current_user):
    router = APIRouter(prefix="/api/trash", tags=["Trash management"])

    @router.get("/settings")
    def get_retention(user=Depends(get_current_user)):
        conn, cursor = _connection(get_connection)
        try:
            cursor.execute("SELECT trash_retention_days FROM users WHERE id=%s", (user["id"],))
            data = cursor.fetchone()
            return {"days": int(data["trash_retention_days"])}
        finally:
            cursor.close()
            conn.close()

    @router.put("/settings")
    def set_retention(data: RetentionSetting, user=Depends(get_current_user)):
        conn, cursor = _connection(get_connection)
        try:
            cursor.execute(
                "UPDATE users SET trash_retention_days=%s WHERE id=%s",
                (data.days, user["id"]),
            )
            conn.commit()
            return {"days": data.days}
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    @router.delete("/photos/{photo_id}")
    def permanently_delete(photo_id: int, user=Depends(get_current_user)):
        purge_one(get_connection, user["id"], photo_id)
        # Best effort immediately. Failed file operations stay in the queue.
        drain_file_queue(get_connection, 100)
        return {"status": "permanently_deleted"}

    @router.post("/empty")
    def empty_trash(user=Depends(get_current_user)):
        result = purge_user_batch(get_connection, user["id"])
        drain_file_queue(get_connection, 300)
        return result

    return router
