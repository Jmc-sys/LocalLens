
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from photos import database


class AlbumCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=5000)


class AlbumPhotos(BaseModel):
    photo_ids: list[int] = Field(
        min_length=1, max_length=500
    )


def build_album_router(get_connection, get_current_user):

    router = APIRouter(
        prefix="/api/albums",
        tags=["Albums"]
    )

    def owned_album(cursor, album_id, user_id):
        cursor.execute(
            """
            SELECT * FROM albums
            WHERE id = %s AND user_id = %s
            """,
            (album_id, user_id)
        )

        album = cursor.fetchone()

        if not album:
            raise HTTPException(404, "Album not found")

        return album

    @router.get("")
    def list_albums(user=Depends(get_current_user)):
        with database(get_connection) as (conn, cursor):
            cursor.execute(
                """
                SELECT a.id, a.name, a.description,
                       a.created_at,
                       COUNT(p.id) AS photo_count,
                       MAX(p.id) AS cover_photo_id
                FROM albums a
                LEFT JOIN album_photos ap
                    ON ap.album_id = a.id
                LEFT JOIN photos p
                    ON p.id = ap.photo_id
                    AND p.user_id = a.user_id
                    AND p.deleted_at IS NULL
                WHERE a.user_id = %s
                GROUP BY a.id
                ORDER BY a.created_at DESC
                """,
                (user["id"],)
            )

            return cursor.fetchall()

    @router.post("")
    def create_album(
        data: AlbumCreate,
        user=Depends(get_current_user)
    ):
        name = data.name.strip()

        if not name:
            raise HTTPException(400, "Album name required")

        with database(get_connection) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO albums (
                    user_id, name, description
                )
                VALUES (%s, %s, %s)
                """,
                (user["id"], name, data.description)
            )

            album_id = cursor.lastrowid
            conn.commit()

            return {"id": album_id, "name": name}

    @router.patch("/{album_id}")
    def rename_album(
        album_id: int,
        data: AlbumCreate,
        user=Depends(get_current_user)
    ):
        name = data.name.strip()

        if not name:
            raise HTTPException(400, "Album name required")

        with database(get_connection) as (conn, cursor):
            owned_album(cursor, album_id, user["id"])

            cursor.execute(
                """
                UPDATE albums
                SET name = %s, description = %s
                WHERE id = %s AND user_id = %s
                """,
                (
                    name, data.description,
                    album_id, user["id"]
                )
            )

            conn.commit()
            return {"status": "updated"}

    @router.delete("/{album_id}")
    def delete_album(
        album_id: int,
        user=Depends(get_current_user)
    ):
        with database(get_connection) as (conn, cursor):
            owned_album(cursor, album_id, user["id"])

            cursor.execute(
                """
                DELETE FROM albums
                WHERE id = %s AND user_id = %s
                """,
                (album_id, user["id"])
            )

            conn.commit()
            return {"status": "deleted"}

    @router.get("/{album_id}/photos")
    def album_photos(
        album_id: int,
        user=Depends(get_current_user)
    ):
        with database(get_connection) as (conn, cursor):
            owned_album(cursor, album_id, user["id"])

            cursor.execute(
                """
                SELECT p.id, p.original_filename,
                       p.width, p.height, p.size_bytes,
                       p.uploaded_at, p.captured_at,
                       p.is_favorite, p.mime_type
                FROM photos p
                INNER JOIN album_photos ap
                    ON p.id = ap.photo_id
                WHERE ap.album_id = %s
                    AND p.user_id = %s
                    AND p.deleted_at IS NULL
                ORDER BY p.uploaded_at DESC
                """,
                (album_id, user["id"])
            )

            return cursor.fetchall()

    @router.post("/{album_id}/photos")
    def add_photos(
        album_id: int,
        data: AlbumPhotos,
        user=Depends(get_current_user)
    ):
        added = 0

        with database(get_connection) as (conn, cursor):
            owned_album(cursor, album_id, user["id"])

            for photo_id in set(data.photo_ids):
                cursor.execute(
                    """
                    INSERT INTO album_photos (
                        album_id, photo_id
                    )
                    SELECT a.id, p.id
                    FROM albums a
                    INNER JOIN photos p
                        ON p.user_id = a.user_id
                    WHERE a.id = %s
                        AND a.user_id = %s
                        AND p.id = %s
                        AND p.deleted_at IS NULL
                    ON DUPLICATE KEY UPDATE
                        added_at = album_photos.added_at
                    """,
                    (album_id, user["id"], photo_id)
                )

                added += cursor.rowcount == 1

            conn.commit()

            return {"status": "updated", "added": added}

    @router.delete("/{album_id}/photos/{photo_id}")
    def remove_photo(
        album_id: int,
        photo_id: int,
        user=Depends(get_current_user)
    ):
        with database(get_connection) as (conn, cursor):
            owned_album(cursor, album_id, user["id"])

            cursor.execute(
                """
                DELETE ap FROM album_photos ap
                INNER JOIN albums a ON a.id = ap.album_id
                WHERE ap.album_id = %s
                    AND ap.photo_id = %s
                    AND a.user_id = %s
                """,
                (album_id, photo_id, user["id"])
            )

            conn.commit()
            return {"status": "removed"}

    return router
