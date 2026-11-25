from family_group import family_album_id_for_cursor
"""Shared Albums: admin-managed membership; owner-contributed media.

Authorized members may add their own original media, view and download all shared
items, and unshare only items they originally own. No original deletion routes.
"""
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageOps, UnidentifiedImageError
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse, Response
from pydantic import BaseModel, Field

from guard import database
from photos import MEDIA_ROOT
from security import JWT_SECRET

TICKET_ISSUER = 'locallens-shared-media'
TICKET_AUDIENCE = 'locallens-shared-stream'
TICKET_MINUTES = 60
CHUNK_SIZE = 512 * 1024


class IdSelection(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)


def unique_ids(ids):
    result = list(dict.fromkeys(ids))
    if not result or any(not isinstance(i, int) or isinstance(i, bool) or i <= 0 for i in result):
        raise HTTPException(422, 'Provide valid positive IDs')
    return result


def safe_media_path(user_id: int, recorded_path: str, directory: str) -> Path:
    """Resolve original only under the actual owner's storage directory."""
    if directory not in ('originals', 'thumbnails', 'resources') or not recorded_path:
        raise HTTPException(404, 'Media file unavailable')
    root = (MEDIA_ROOT / 'users' / str(user_id) / directory).resolve()
    path = Path(recorded_path).resolve()
    if not path.is_relative_to(root) or not path.is_file() or not path.is_absolute():
        raise HTTPException(404, 'Media file unavailable')
    return path


def _chunks(path, start, end):
    with open(path, 'rb') as stream:
        stream.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = stream.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            yield chunk
            remaining -= len(chunk)


def range_response(path, mime, requested_range, download_name=None):
    """Range-aware file streaming for browser video seeking without RAM copies."""
    size = path.stat().st_size
    if not size:
        raise HTTPException(404, 'Empty media file')
    start, end = 0, size - 1
    status = 200
    if requested_range:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested_range.strip())
        if not match or not (match[1] or match[2]):
            raise HTTPException(416, 'Unsupported byte range', headers={'Content-Range': f'bytes */{size}'})
        if not match[1]:
            suffix = int(match[2])
            if suffix == 0:
                raise HTTPException(416, 'Invalid suffix range', headers={'Content-Range': f'bytes */{size}'})
            start = max(0, size - suffix)
        else:
            start = int(match[1])
            end = min(size - 1, int(match[2])) if match[2] else size - 1
        if start >= size or end < start:
            raise HTTPException(416, 'Range outside file', headers={'Content-Range': f'bytes */{size}'})
        status = 206
    headers = {
        'Accept-Ranges': 'bytes',
        'Content-Length': str(end - start + 1),
        'Cache-Control': 'private, no-store',
        'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff',
    }
    if status == 206:
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    if download_name:
        headers['Content-Disposition'] = "attachment; filename*=UTF-8''" + quote(download_name, safe='')
    return StreamingResponse(_chunks(path, start, end), status_code=status, media_type=mime,
                             headers=headers)


def build_shared_album_router(get_connection, get_current_user):
    router = APIRouter(prefix='/api/shared-albums', tags=['Shared Albums'])

    def allowed_album(cursor, album_id, user):
        cursor.execute('''SELECT a.id,a.name,a.description,a.created_at
            FROM shared_albums a WHERE a.id=%s AND
            (%s='admin' OR EXISTS (SELECT 1 FROM shared_album_members m
               WHERE m.album_id=a.id AND m.user_id=%s))''',
               (album_id, user['role'], user['id']))
        album = cursor.fetchone()
        if not album:
            raise HTTPException(404, 'Shared album not found or access revoked')
        return album

    def album_media(cursor, album_id, photo_id, user):
        album = allowed_album(cursor, album_id, user)
        cursor.execute('''SELECT p.id,p.user_id,p.original_filename,p.mime_type,
            p.media_type,p.storage_path,p.thumbnail_path,p.size_bytes,
            u.username AS owner_username
            FROM shared_album_items i JOIN photos p ON p.id=i.photo_id
            JOIN users u ON u.id=p.user_id
            WHERE i.album_id=%s AND i.photo_id=%s AND p.deleted_at IS NULL
              AND u.is_active=1''', (album_id, photo_id))
        media = cursor.fetchone()
        if not media:
            raise HTTPException(404, 'Media not shared or owner removed it')
        return album, media

    def ticket_user(cursor, ticket, album_id, photo_id, purpose):
        try:
            claims = jwt.decode(ticket, JWT_SECRET, algorithms=['HS256'],
                                audience=TICKET_AUDIENCE, issuer=TICKET_ISSUER,
                                options={'require': ['exp','iat','sub','album','photo','purpose']})
            user_id = int(claims['sub'])
            if not user_id or int(claims['album']) != album_id or \
                    int(claims['photo']) != photo_id or claims['purpose'] != purpose:
                raise ValueError('Ticket does not match resource')
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(401, 'Shared media access expired or invalid') from exc
        cursor.execute('SELECT id,role,is_active FROM users WHERE id=%s', (user_id,))
        user = cursor.fetchone()
        if not user or not user['is_active']:
            raise HTTPException(401, 'Account unavailable')
        return user

    def make_ticket(user_id, album_id, photo_id, purpose):
        now = datetime.now(timezone.utc)
        claims = {'sub': str(user_id), 'album': album_id, 'photo': photo_id,
                  'purpose': purpose, 'iat': now,
                  'exp': now + timedelta(minutes=TICKET_MINUTES),
                  'iss': TICKET_ISSUER, 'aud': TICKET_AUDIENCE}
        return jwt.encode(claims, JWT_SECRET, algorithm='HS256')

    @router.get('')
    def list_albums(user=Depends(get_current_user)):
        with database(get_connection) as (conn, cur):
            cur.execute('''SELECT a.id,a.name,a.description,a.created_at,
                (SELECT COUNT(*) FROM shared_album_items i JOIN photos p ON p.id=i.photo_id
                 WHERE i.album_id=a.id AND p.deleted_at IS NULL) AS item_count,
                (SELECT COUNT(*) FROM shared_album_members m WHERE m.album_id=a.id) AS member_count
                FROM shared_albums a
                WHERE %s='admin' OR EXISTS (SELECT 1 FROM shared_album_members m
                    WHERE m.album_id=a.id AND m.user_id=%s)
                ORDER BY a.created_at DESC,a.id DESC''', (user['role'], user['id']))
            albums = cur.fetchall()
            # ll_random_cover: choose a different original photo when the
            # Albums tab fetches this list. Random seek avoids ORDER BY RAND()
            # over every photo in a large family album.
            import secrets
            for album in albums:
                album['cover_photo_id'] = None
                cur.execute("""SELECT MIN(i.photo_id) AS lo, MAX(i.photo_id) AS hi
                    FROM shared_album_items i JOIN photos p ON p.id=i.photo_id
                    JOIN users u ON u.id=p.user_id
                    WHERE i.album_id=%s AND p.deleted_at IS NULL
                      AND u.is_active=1 AND COALESCE(p.media_type,'photo') <> 'video'""",
                    (album['id'],))
                bounds = cur.fetchone()
                if not bounds or bounds['lo'] is None:
                    continue
                threshold = secrets.randbelow(int(bounds['hi']) - int(bounds['lo']) + 1) + int(bounds['lo'])
                for condition, params in (
                    ('AND i.photo_id >= %s', (album['id'], threshold)),
                    ('', (album['id'],)),
                ):
                    cur.execute(f"""SELECT i.photo_id AS id
                        FROM shared_album_items i JOIN photos p ON p.id=i.photo_id
                        JOIN users u ON u.id=p.user_id
                        WHERE i.album_id=%s AND p.deleted_at IS NULL
                          AND u.is_active=1 AND COALESCE(p.media_type,'photo') <> 'video'
                          {condition}
                        ORDER BY i.photo_id LIMIT 1""", params)
                    chosen = cur.fetchone()
                    if chosen:
                        album['cover_photo_id'] = chosen['id']
                        break
            return albums

    @router.get('/{album_id}')
    def get_album(album_id: int, limit: int = Query(100, ge=1, le=200),
                  offset: int = Query(0, ge=0), user=Depends(get_current_user)):
        with database(get_connection) as (conn, cur):
            album = allowed_album(cur, album_id, user)
            cur.execute('''SELECT p.id,p.user_id,p.original_filename,p.mime_type,p.media_type,
                p.uploaded_at,p.size_bytes,u.username AS owner_username,
                EXISTS(SELECT 1 FROM photo_resources r WHERE r.photo_id=p.id
                  AND r.resource_type='live_video') AS has_live_motion
                FROM shared_album_items i JOIN photos p ON p.id=i.photo_id
                JOIN users u ON u.id=p.user_id WHERE i.album_id=%s
                AND p.deleted_at IS NULL AND u.is_active=1
                ORDER BY i.added_at DESC,p.id DESC LIMIT %s OFFSET %s''',
                (album_id,limit+1,offset))
            items = cur.fetchall()
            has_more = len(items) > limit
            items = items[:limit]
            if user['role'] == 'admin':
                cur.execute('SELECT user_id FROM shared_album_members WHERE album_id=%s', (album_id,))
                members = [row['user_id'] for row in cur.fetchall()]
            else:
                members = []
            album['is_family'] = family_album_id_for_cursor(cur) == album_id
            return {'album': album, 'items': items, 'members': members,
                    'has_more': has_more}

    @router.post('/{album_id}/items')
    def add_items(album_id: int, body: IdSelection, user=Depends(get_current_user)):
        ids = unique_ids(body.ids)
        with database(get_connection) as (conn, cur):
            allowed_album(cur, album_id, user)
            placeholders = ','.join(['%s'] * len(ids))
            cur.execute(f"""SELECT p.id FROM photos p WHERE p.user_id=%s
                AND p.id IN ({placeholders}) AND p.deleted_at IS NULL""",
                (user['id'], *ids))
            if {r['id'] for r in cur.fetchall()} != set(ids):
                raise HTTPException(403, 'You may only share your own available media')
            cur.executemany('INSERT IGNORE INTO shared_album_items(album_id,photo_id) VALUES(%s,%s)',
                            [(album_id, i) for i in ids])
            conn.commit()
            return {'added': len(ids)}

    @router.post('/{album_id}/items/remove-owned')
    def remove_owned_items(album_id: int, body: IdSelection, user=Depends(get_current_user)):
        # Owner-only, batch removal. Unsharing never deletes an original or thumbnail.
        ids = unique_ids(body.ids)
        marks = ','.join(['%s'] * len(ids))
        with database(get_connection) as (conn, cur):
            allowed_album(cur, album_id, user)
            cur.execute(f"""SELECT i.photo_id FROM shared_album_items i
                JOIN photos p ON p.id=i.photo_id
                WHERE i.album_id=%s AND p.user_id=%s
                  AND i.photo_id IN ({marks})""", (album_id, user['id'], *ids))
            if {row['photo_id'] for row in cur.fetchall()} != set(ids):
                raise HTTPException(403, 'Only the original owner may remove shared items')
            cur.execute(f"DELETE FROM shared_album_items WHERE album_id=%s AND photo_id IN ({marks})",
                        (album_id, *ids))
            count = cur.rowcount
            conn.commit()
        return {'removed': count}

    @router.delete('/{album_id}/items/{photo_id}', status_code=204)
    def remove_item(album_id: int, photo_id: int, user=Depends(get_current_user)):
        with database(get_connection) as (conn, cur):
            allowed_album(cur, album_id, user)
            # Admin access does NOT override original ownership.
            cur.execute("""SELECT p.user_id FROM shared_album_items i
                JOIN photos p ON p.id=i.photo_id
                WHERE i.album_id=%s AND i.photo_id=%s""", (album_id,photo_id))
            item = cur.fetchone()
            if not item:
                raise HTTPException(404, 'Shared item not found')
            if item['user_id'] != user['id']:
                raise HTTPException(403, 'Only the original owner may remove this item')
            cur.execute('DELETE FROM shared_album_items WHERE album_id=%s AND photo_id=%s',
                        (album_id,photo_id))
            conn.commit()
        # Unshares only, never touches original storage or the trash.

    @router.get('/{album_id}/media/{photo_id}/preview')
    def authorized_preview(album_id: int, photo_id: int,
                           user=Depends(get_current_user)):
        # Verify member access on EVERY request, even a previously viewed item.
        with database(get_connection) as (_, cur):
            _, media = album_media(cur, album_id, photo_id, user)
        if media['media_type'] == 'video' or media['mime_type'].startswith('video/'):
            raise HTTPException(415, 'Not an image')
        path = safe_media_path(media['user_id'], media['storage_path'], 'originals')
        mime = media['mime_type'].lower()
        headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}
        if mime in ('image/jpeg','image/png','image/webp','image/gif'):
            return FileResponse(path, media_type=mime, headers=headers)
        # Convert unsupported browser formats (including HEIC) without modifying
        # the stored original. Pixel dimensions are bounded for safe viewing.
        try:
            with Image.open(path) as opened:
                oriented = ImageOps.exif_transpose(opened)
                oriented.thumbnail((2500, 2500))
                if oriented.mode != 'RGB':
                    oriented = oriented.convert('RGB')
                buffer = BytesIO()
                oriented.save(buffer, format='JPEG', quality=84)
            return Response(content=buffer.getvalue(), media_type='image/jpeg', headers=headers)
        except (UnidentifiedImageError, OSError, ValueError):
            thumbnail_path = safe_media_path(media['user_id'], media['thumbnail_path'], 'thumbnails')
            return FileResponse(thumbnail_path, media_type='image/jpeg', headers=headers)

    @router.get('/{album_id}/media/{photo_id}/thumbnail')
    def thumbnail(album_id: int, photo_id: int, user=Depends(get_current_user)):
        with database(get_connection) as (conn, cur):
            _, media = album_media(cur, album_id, photo_id, user)
        path = safe_media_path(media['user_id'], media['thumbnail_path'], 'thumbnails')
        return FileResponse(path, media_type='image/jpeg', headers={
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})

    @router.post('/{album_id}/media/{photo_id}/access-url')
    def access_url(album_id: int, photo_id: int, user=Depends(get_current_user)):
        with database(get_connection) as (conn, cur):
            _, media = album_media(cur, album_id, photo_id, user)
        playback = media['media_type'] == 'video' or media['mime_type'].startswith('video/')
        purpose = 'stream' if playback else 'download'
        token = make_ticket(user['id'], album_id, photo_id, purpose)
        endpoint = 'stream' if playback else 'download'
        return {'url': f'/api/shared-albums/{album_id}/media/{photo_id}/{endpoint}?ticket={quote(token)}',
                'expires_in': TICKET_MINUTES * 60, 'video': playback}

    @router.post('/{album_id}/media/{photo_id}/motion-access-url')
    def motion_access_url(album_id: int, photo_id: int, user=Depends(get_current_user)):
        with database(get_connection) as (conn, cur):
            _, media = album_media(cur, album_id, photo_id, user)
            cur.execute("SELECT 1 FROM photo_resources WHERE photo_id=%s AND resource_type='live_video' LIMIT 1",
                        (photo_id,))
            if not cur.fetchone():
                raise HTTPException(404, 'Motion original unavailable')
        token = make_ticket(user['id'], album_id, photo_id, 'motion')
        return {'url': f'/api/shared-albums/{album_id}/media/{photo_id}/motion-download?ticket={quote(token)}',
                'expires_in': TICKET_MINUTES * 60}

    @router.post('/{album_id}/media/{photo_id}/motion-play-url')
    def motion_play_url(album_id: int, photo_id: int, user=Depends(get_current_user)):
        """Issue a short-lived playback ticket only to authorized shared-album members."""
        with database(get_connection) as (conn, cur):
            album_media(cur, album_id, photo_id, user)
            cur.execute("""SELECT 1 FROM photo_resources
                WHERE photo_id=%s AND resource_type='live_video' LIMIT 1""", (photo_id,))
            if not cur.fetchone():
                raise HTTPException(404, 'Live Photo motion file unavailable')
        ticket = make_ticket(user['id'], album_id, photo_id, 'motion_stream')
        return {
            'url': f'/api/shared-albums/{album_id}/media/{photo_id}/motion-stream?ticket={quote(ticket)}',
            'expires_in': TICKET_MINUTES * 60,
        }

    @router.get('/{album_id}/media/{photo_id}/motion-stream')
    def motion_stream(album_id: int, photo_id: int, request: Request, ticket: str):
        """Stream the original companion MOV with Range support; no file copying."""
        with database(get_connection) as (conn, cur):
            user = ticket_user(cur, ticket, album_id, photo_id, 'motion_stream')
            _, photo = album_media(cur, album_id, photo_id, user)
            cur.execute("""SELECT storage_path FROM photo_resources
                WHERE photo_id=%s AND resource_type='live_video' LIMIT 1""", (photo_id,))
            motion = cur.fetchone()
        if not motion:
            raise HTTPException(404, 'Live Photo motion file unavailable')
        original = safe_media_path(photo['user_id'], motion['storage_path'], 'resources')
        return range_response(original, 'video/quicktime', request.headers.get('range'))

    @router.post('/{album_id}/media/{photo_id}/bundle-access-url')
    def bundle_access_url(album_id: int, photo_id: int, user=Depends(get_current_user)):
        # Authenticate member and verify that this media is still shared.
        with database(get_connection) as (conn, cur):
            album_media(cur, album_id, photo_id, user)
        token = make_ticket(user['id'], album_id, photo_id, 'all_originals')
        return {'url': f'/api/shared-albums/{album_id}/media/{photo_id}/bundle-download?ticket={quote(token)}',
                'expires_in': TICKET_MINUTES * 60}

    @router.get('/{album_id}/media/{photo_id}/bundle-download')
    def bundle_download(album_id: int, photo_id: int, ticket: str):
        import os
        import shutil
        import tempfile
        import zipfile
        from starlette.background import BackgroundTask
        with database(get_connection) as (conn, cur):
            user = ticket_user(cur, ticket, album_id, photo_id, 'all_originals')
            _, media = album_media(cur, album_id, photo_id, user)
            cur.execute("""SELECT storage_path,original_filename FROM photo_resources
                           WHERE photo_id=%s AND resource_type='live_video' LIMIT 1""", (photo_id,))
            motion = cur.fetchone()
        original = safe_media_path(media['user_id'], media['storage_path'], 'originals')
        private_headers = {'Cache-Control': 'private, no-store', 'Referrer-Policy': 'no-referrer',
                           'X-Content-Type-Options': 'nosniff'}
        if not motion:
            return FileResponse(original, media_type='application/octet-stream',
                                filename=media['original_filename'], content_disposition_type='attachment',
                                headers=private_headers)
        video = safe_media_path(media['user_id'], motion['storage_path'], 'resources')
        if shutil.disk_usage(video.parent).free < (int(os.getenv('MIN_FREE_DISK_GB', '10')) * 1024**3) + original.stat().st_size + video.stat().st_size + 65536:
            raise HTTPException(507, 'Insufficient storage to prepare complete originals')
        fd, filename = tempfile.mkstemp(prefix='.ll-bundle-', suffix='.zip', dir=str(video.parent))
        os.close(fd)
        archive_path = Path(filename)
        try:
            still_name = Path(str(media['original_filename']).replace('\\', '/')).name
            motion_name = Path(str(motion['original_filename']).replace('\\', '/')).name
            if still_name in ('', '.', '..') or motion_name in ('', '.', '..'):
                raise HTTPException(422, 'Original file name unavailable')
            if still_name.casefold() == motion_name.casefold():
                motion_name = 'motion-' + motion_name
            with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_STORED,
                                 allowZip64=True) as archive:
                archive.write(original, arcname=still_name)
                archive.write(video, arcname=motion_name)
            return FileResponse(archive_path, media_type='application/zip',
                                filename=f'LivePhoto-{photo_id}.zip', content_disposition_type='attachment',
                                headers=private_headers,
                                background=BackgroundTask(archive_path.unlink, missing_ok=True))
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise

    @router.get('/{album_id}/media/{photo_id}/motion-download')
    def motion_download(album_id: int, photo_id: int, ticket: str):
        with database(get_connection) as (conn, cur):
            user = ticket_user(cur, ticket, album_id, photo_id, 'motion')
            _, media = album_media(cur, album_id, photo_id, user)
            cur.execute("""SELECT storage_path,original_filename FROM photo_resources
                WHERE photo_id=%s AND resource_type='live_video' LIMIT 1""", (photo_id,))
            motion = cur.fetchone()
        if not motion:
            raise HTTPException(404, 'Motion original unavailable')
        path = safe_media_path(media['user_id'], motion['storage_path'], 'resources')
        return FileResponse(path, media_type='application/octet-stream',
                            filename=motion['original_filename'], content_disposition_type='attachment',
                            headers={'Cache-Control':'private, no-store', 'Referrer-Policy':'no-referrer',
                                     'X-Content-Type-Options':'nosniff'})

    @router.get('/{album_id}/media/{photo_id}/download')
    def download(album_id: int, photo_id: int, ticket: str):
        with database(get_connection) as (conn, cur):
            user = ticket_user(cur, ticket, album_id, photo_id, 'download')
            _, media = album_media(cur, album_id, photo_id, user)
        path = safe_media_path(media['user_id'], media['storage_path'], 'originals')
        return FileResponse(path, media_type='application/octet-stream',
                            filename=media['original_filename'], content_disposition_type='attachment',
                            headers={'Cache-Control':'private, no-store', 'Referrer-Policy':'no-referrer',
                                     'X-Content-Type-Options':'nosniff'})

    @router.get('/{album_id}/media/{photo_id}/stream')
    def stream(album_id: int, photo_id: int, request: Request, ticket: str):
        with database(get_connection) as (conn, cur):
            user = ticket_user(cur, ticket, album_id, photo_id, 'stream')
            _, media = album_media(cur, album_id, photo_id, user)
        if media['media_type'] != 'video' and not media['mime_type'].startswith('video/'):
            raise HTTPException(415, 'Not a video')
        path = safe_media_path(media['user_id'], media['storage_path'], 'originals')
        return range_response(path, media['mime_type'], request.headers.get('range'),
                              download_name=media['original_filename'] if request.query_params.get('download') == '1' else None)

    return router
