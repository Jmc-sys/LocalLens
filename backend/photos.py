import os
import uuid
import hashlib
import shutil
import warnings

from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()
from fastapi import (
    APIRouter, Depends, HTTPException,
    UploadFile, File, Query
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


MEDIA_ROOT = Path(
    os.getenv("MEDIA_ROOT", "/storage")
).resolve()

MAX_UPLOAD_BYTES = (
    int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024**2
)

MIN_FREE_BYTES = (
    int(os.getenv("MIN_FREE_DISK_GB", "10")) * 1024**3
)

PREVIEW_MAX_SIZE = (2560, 2560)
PREVIEW_QUALITY = 92

Image.MAX_IMAGE_PIXELS = 80_000_000

IMAGE_FORMATS = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
    "GIF": (".gif", "image/gif"),
    "TIFF": (".tiff", "image/tiff"),
    "BMP": (".bmp", "image/bmp"),
    "HEIF": (".heic", "image/heic"),
    "HEIC": (".heic", "image/heic"),
}


class PhotoUpdate(BaseModel):
    is_favorite: bool | None = None
    description: str | None = Field(
        default=None, max_length=5000
    )


@contextmanager
def database(get_connection):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        yield conn, cursor
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def build_photo_router(get_connection, get_current_user):

    router = APIRouter(
        prefix="/api/photos",
        tags=["Photos"]
    )

    def owned_photo(cursor, photo_id, user_id):
        cursor.execute(
            """
            SELECT * FROM photos
            WHERE id = %s AND user_id = %s
            """,
            (photo_id, user_id)
        )

        photo = cursor.fetchone()

        if not photo:
            raise HTTPException(404, "Photo not found")

        return photo

    @router.get("")
    def list_photos(
        sort: str = "newest",
        search: str = Query("", max_length=255),
        favorite: bool = False,
        trash: bool = False,
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0),
        user=Depends(get_current_user)
    ):
        sorting = {
            "newest": "uploaded_at DESC",
            "oldest": "uploaded_at ASC",
            "captured": "COALESCE(captured_at, uploaded_at) DESC",
            "name_asc": "original_filename ASC",
            "name_desc": "original_filename DESC",
            "largest": "size_bytes DESC",
            "smallest": "size_bytes ASC",
        }

        order = sorting.get(sort, sorting["newest"])

        conditions = ["user_id = %s"]
        params = [user["id"]]

        conditions.append(
            "deleted_at IS NOT NULL"
            if trash else
            "deleted_at IS NULL"
        )

        if favorite:
            conditions.append("is_favorite = TRUE")

        if search:
            conditions.append(
                "(original_filename LIKE %s "
                "OR description LIKE %s)"
            )
            params.extend([f"%{search}%"] * 2)

        where = " AND ".join(conditions)

        with database(get_connection) as (conn, cursor):
            cursor.execute(
                f"""
                SELECT id, original_filename, mime_type,
                       size_bytes, width, height,
                       captured_at, uploaded_at,
                       is_favorite, description, deleted_at
                FROM photos
                WHERE {where}
                ORDER BY {order}, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset)
            )

            return cursor.fetchall()

    @router.post("/upload")
    def upload_photo(
        file: UploadFile = File(...),
        user=Depends(get_current_user)
    ):
        user_id = user["id"]

        root = MEDIA_ROOT / "users" / str(user_id)
        originals = root / "originals"
        thumbnails = root / "thumbnails"

        originals.mkdir(parents=True, exist_ok=True)
        thumbnails.mkdir(parents=True, exist_ok=True)

        unique_id = uuid.uuid4().hex
        temp_path = originals / f"{unique_id}.upload"
        original_path = None
        thumbnail_path = None
        committed = False

        filename = (
            (file.filename or "photo")
            .replace("\\", "/").split("/")[-1][:255]
        ) or "photo"

        digest = hashlib.sha256()
        size = 0

        try:
            with temp_path.open("wb") as output:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)

                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            413, "File exceeds upload limit"
                        )

                    if shutil.disk_usage(MEDIA_ROOT).free < (
                        MIN_FREE_BYTES + len(chunk)
                    ):
                        raise HTTPException(
                            507, "Insufficient storage space"
                        )

                    digest.update(chunk)
                    output.write(chunk)

            sha256 = digest.hexdigest()

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter(
                        "error",
                        Image.DecompressionBombWarning
                    )

                    with Image.open(temp_path) as image:
                        image_format = image.format
                        image.verify()

                    if image_format not in IMAGE_FORMATS:
                        raise HTTPException(
                            415, "Unsupported image format"
                        )

                    extension, mime_type = (
                        IMAGE_FORMATS[image_format]
                    )

                    with Image.open(temp_path) as image:
                        captured_at = None
                        exif = image.getexif()
                        try:
                            exif_details = exif.get_ifd(34665)
                        except (KeyError, ValueError, TypeError):
                            exif_details = {}

                        date = (
                            exif_details.get(36867)
                            or exif_details.get(36868)
                            or exif.get(36867)
                            or exif.get(306)
                        )

                        if date:
                            try:
                                captured_at = datetime.strptime(
                                    str(date),
                                    "%Y:%m:%d %H:%M:%S"
                                )
                            except ValueError:
                                pass

                        image = ImageOps.exif_transpose(image)
                        width, height = image.size

                        image.thumbnail(
                            (480, 480),
                            Image.Resampling.LANCZOS
                        )

                        thumbnail_path = (
                            thumbnails / f"{unique_id}.jpg"
                        )

                        image.convert("RGB").save(
                            thumbnail_path,
                            "JPEG",
                            quality=85
                        )

            except (
                UnidentifiedImageError,
                OSError,
                Image.DecompressionBombError,
                Image.DecompressionBombWarning,
            ):
                raise HTTPException(
                    415, "Invalid or unsupported image"
                )

            with database(get_connection) as (conn, cursor):

                # Serialize uploads for this account.
                cursor.execute(
                    """
                    SELECT storage_quota_bytes FROM users
                    WHERE id = %s FOR UPDATE
                    """,
                    (user_id,)
                )

                account = cursor.fetchone()

                cursor.execute(
                    """
                    SELECT id, deleted_at FROM photos
                    WHERE user_id = %s AND sha256 = %s
                    LIMIT 1
                    """,
                    (user_id, sha256)
                )

                existing = cursor.fetchone()

                if existing:
                    return {
                        "status": "duplicate",
                        "id": existing["id"],
                        "in_trash": bool(existing["deleted_at"]),
                        "filename": filename
                    }

                quota = account["storage_quota_bytes"]

                if quota is not None:
                    cursor.execute(
                        """
                        SELECT COALESCE(SUM(size_bytes), 0) AS used
                        FROM photos WHERE user_id = %s
                        """,
                        (user_id,)
                    )

                    used = cursor.fetchone()["used"]

                    if used + size > quota:
                        raise HTTPException(
                            507, "Account storage quota exceeded"
                        )

                original_path = originals / (
                    unique_id + extension
                )

                temp_path.replace(original_path)

                cursor.execute(
                    """
                    INSERT INTO photos (
                        user_id, original_filename,
                        storage_path, thumbnail_path,
                        mime_type, size_bytes,
                        width, height, sha256, captured_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        user_id, filename,
                        str(original_path),
                        str(thumbnail_path),
                        mime_type, size,
                        width, height, sha256, captured_at
                    )
                )

                photo_id = cursor.lastrowid
                conn.commit()
                committed = True

                return {
                    "status": "uploaded",
                    "id": photo_id,
                    "filename": filename,
                    "size_bytes": size
                }

        finally:
            file.file.close()
            temp_path.unlink(missing_ok=True)

            if not committed:
                if original_path:
                    original_path.unlink(missing_ok=True)
                if thumbnail_path:
                    thumbnail_path.unlink(missing_ok=True)

    @router.get("/{photo_id}/thumbnail")
    def thumbnail(
        photo_id: int,
        user=Depends(get_current_user)
    ):
        with database(get_connection) as (conn, cursor):
            photo = owned_photo(
                cursor, photo_id, user["id"]
            )

        path = Path(photo["thumbnail_path"] or "").resolve()

        if not path.is_relative_to(
            MEDIA_ROOT / "users" / str(user["id"])
        ) or not path.is_file():
            raise HTTPException(404, "Thumbnail unavailable")

        return FileResponse(
            path,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, no-store"}
        )

    @router.get("/{photo_id}/file")
    def original(
        photo_id: int,
        download: bool = False,
        user=Depends(get_current_user)
    ):
        with database(get_connection) as (conn, cursor):
            photo = owned_photo(
                cursor, photo_id, user["id"]
            )

        path = Path(photo["storage_path"]).resolve()

        if not path.is_relative_to(
            MEDIA_ROOT / "users" / str(user["id"])
        ) or not path.is_file():
            raise HTTPException(404, "Original file unavailable")

        return FileResponse(
            path,
            media_type=photo["mime_type"],
            filename=photo["original_filename"],
            content_disposition_type=(
                "attachment" if download else "inline"
            ),
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff"
            }
        )

    
    @router.get("/{photo_id}/preview")
    def photo_preview(
        photo_id: int,
        user=Depends(get_current_user)
    ):
        user_id = user["id"]

        with database(get_connection) as (conn, cursor):
            photo = owned_photo(
                cursor, photo_id, user_id
            )

        user_root = (
            MEDIA_ROOT / "users" / str(user_id)
        ).resolve()

        original_path = Path(
            photo["storage_path"]
        ).resolve()

        if (
            not original_path.is_relative_to(user_root)
            or not original_path.is_file()
        ):
            raise HTTPException(
                404, "Original image unavailable"
            )

        # Browser-compatible formats can be displayed
        # directly without generating another file.
        browser_formats = {
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/gif",
        }

        if photo["mime_type"] in browser_formats:
            return FileResponse(
                original_path,
                media_type=photo["mime_type"],
                headers={
                    "Cache-Control": "private, no-store",
                    "X-Content-Type-Options": "nosniff"
                }
            )

        preview_dir = user_root / "previews"
        preview_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        preview_path = (
            preview_dir / f"{photo_id}.jpg"
        )

        if not preview_path.is_file():

            if shutil.disk_usage(MEDIA_ROOT).free < (
                MIN_FREE_BYTES + 32 * 1024**2
            ):
                raise HTTPException(
                    507, "Insufficient preview storage"
                )

            temp_path = preview_dir / (
                f"{photo_id}_{uuid.uuid4().hex}.tmp"
            )

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter(
                        "error",
                        Image.DecompressionBombWarning
                    )

                    with Image.open(original_path) as image:

                        image = ImageOps.exif_transpose(
                            image
                        )

                        image.thumbnail(
                            PREVIEW_MAX_SIZE,
                            Image.Resampling.LANCZOS
                        )

                        image.convert("RGB").save(
                            temp_path,
                            format="JPEG",
                            quality=PREVIEW_QUALITY,
                            optimize=True
                        )

                temp_path.replace(preview_path)

            except (
                OSError,
                ValueError,
                UnidentifiedImageError,
                Image.DecompressionBombError,
                Image.DecompressionBombWarning,
            ):
                raise HTTPException(
                    415,
                    "Unable to generate image preview"
                )

            finally:
                temp_path.unlink(missing_ok=True)

        return FileResponse(
            preview_path,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff"
            }
        )



    @router.patch("/{photo_id}")
    def update_photo(
        photo_id: int,
        data: PhotoUpdate,
        user=Depends(get_current_user)
    ):
        with database(get_connection) as (conn, cursor):
            owned_photo(cursor, photo_id, user["id"])

            for field, value in data.model_dump(
                exclude_unset=True
            ).items():
                if field == "is_favorite" and value is None:
                    continue

                cursor.execute(
                    f"""
                    UPDATE photos SET {field} = %s
                    WHERE id = %s AND user_id = %s
                    """,
                    (value, photo_id, user["id"])
                )

            conn.commit()
            return {"status": "updated"}

    @router.delete("/{photo_id}")
    def trash_photo(
        photo_id: int,
        user=Depends(get_current_user)
    ):
        with database(get_connection) as (conn, cursor):
            owned_photo(cursor, photo_id, user["id"])

            cursor.execute(
                """
                UPDATE photos SET deleted_at = UTC_TIMESTAMP()
                WHERE id = %s AND user_id = %s
                """,
                (photo_id, user["id"])
            )

            conn.commit()
            return {"status": "trashed"}

    @router.post("/{photo_id}/restore")
    def restore_photo(
        photo_id: int,
        user=Depends(get_current_user)
    ):
        with database(get_connection) as (conn, cursor):
            owned_photo(cursor, photo_id, user["id"])

            cursor.execute(
                """
                UPDATE photos SET deleted_at = NULL
                WHERE id = %s AND user_id = %s
                """,
                (photo_id, user["id"])
            )

            conn.commit()
            return {"status": "restored"}
    
    @router.get("/{photo_id}/preview")
    def preview_photo(
        photo_id: int,
        user=Depends(get_current_user)
    ):
        with database(get_connection) as (conn, cursor):
            photo = owned_photo(
                cursor, photo_id, user["id"]
            )

        path = Path(photo["storage_path"]).resolve()

        user_root = (
            MEDIA_ROOT / "users" / str(user["id"])
        ).resolve()

        if (
            not path.is_relative_to(user_root)
            or not path.is_file()
        ):
            raise HTTPException(
                404, "Original file unavailable"
            )

        try:
            with warnings.catch_warnings():
                warnings.simplefilter(
                    "error",
                    Image.DecompressionBombWarning
                )

                with Image.open(path) as image:
                    image = ImageOps.exif_transpose(image)

                    image.thumbnail(
                        (2560, 2560),
                        Image.Resampling.LANCZOS
                    )

                    if (
                        image.mode in ("RGBA", "LA")
                        or "transparency" in image.info
                    ):
                        image = image.convert("RGBA")

                        background = Image.new(
                            "RGBA",
                            image.size,
                            (255, 255, 255, 255)
                        )

                        background.alpha_composite(image)
                        image = background.convert("RGB")
                    else:
                        image = image.convert("RGB")

                    buffer = BytesIO()

                    image.save(
                        buffer,
                        format="JPEG",
                        quality=92,
                        optimize=True
                    )

                    buffer.seek(0)

            return StreamingResponse(
                buffer,
                media_type="image/jpeg",
                headers={
                    "Cache-Control": "private, no-store",
                    "X-Content-Type-Options": "nosniff"
                }
            )

        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning
        ):
            raise HTTPException(
                415,
                "Unable to generate image preview"
            )

    return router
