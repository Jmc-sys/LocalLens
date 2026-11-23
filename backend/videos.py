"""Original-video library: authenticated uploads, JPEG posters, and range streaming.

Standalone videos are rows in photos(media_type='video'), so existing album,
trash, favorite, quota, and cleanup logic can work with either media type.
Live Photo companion MOVs remain photo_resources, not standalone videos.
"""
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from photos import MEDIA_ROOT, MIN_FREE_BYTES, database
from media_names import name_for_duplicate, find_filename_collision, filename_collision_response

VIDEO_MAX_BYTES = int(os.getenv('MAX_VIDEO_UPLOAD_MB', '2048')) * 1024**2
VIDEO_EXTENSIONS = {
    '.mp4': ('video/mp4', ('mov', 'mp4', 'm4a', '3gp', '3g2', 'mj2')),
    '.m4v': ('video/mp4', ('mov', 'mp4', 'm4a', '3gp', '3g2', 'mj2')),
    '.mov': ('video/quicktime', ('mov', 'mp4', 'm4a', '3gp', '3g2', 'mj2')),
    '.webm': ('video/webm', ('matroska', 'webm')),
    '.mkv': ('video/x-matroska', ('matroska', 'webm')),
}


def stage_video_file(upload, user_id):
    """Stream a regular video to disk once; hash during the stream."""
    originals = (MEDIA_ROOT / 'users' / str(user_id) / 'originals').resolve()
    originals.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(originals).free < MIN_FREE_BYTES + 1024 * 1024:
        raise HTTPException(507, 'Insufficient server disk space')
    staging = originals / (uuid.uuid4().hex + '.video-upload')
    digest = hashlib.sha256()
    size = 0
    try:
        with staging.open('xb') as output:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > VIDEO_MAX_BYTES:
                    raise HTTPException(413, 'Video exceeds the configured upload limit')
                if shutil.disk_usage(originals).free < MIN_FREE_BYTES + len(chunk):
                    raise HTTPException(507, 'Insufficient server disk space')
                digest.update(chunk)
                output.write(chunk)
        if size == 0:
            raise HTTPException(415, 'Empty video file')
        return staging, size, digest.hexdigest()
    except Exception:
        staging.unlink(missing_ok=True)
        raise


def save_staged_video(get_connection, user, staging, name, size, sha256,
                      *, on_duplicate='skip', new_name=None):
    """Persist an already-received original without uploading or hashing it again.

    Called by both /api/videos/upload and the single-pass MOV classifier.
    The caller retains ownership of staging cleanup. Database ownership,
    quota and filename checks are performed again under a user row lock.
    """
    if on_duplicate not in ('skip', 'keep'):
        raise HTTPException(422, 'Invalid duplicate decision')
    uid = user['id']
    name = (name or 'video').replace('\\', '/').split('/')[-1][:255]
    suffix = Path(name).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(415, 'Supported videos: MP4, M4V, MOV, WebM and MKV')
    if size <= 0 or size > VIDEO_MAX_BYTES:
        raise HTTPException(413, 'Invalid video upload size')
    original_name = name
    if on_duplicate == 'keep':
        name = name_for_duplicate(new_name, original_name)

    root = (MEDIA_ROOT / 'users' / str(uid)).resolve()
    staging = Path(staging).resolve()
    if not staging.is_relative_to(root) or not staging.is_file():
        raise HTTPException(400, 'Invalid staged upload')
    originals = root / 'originals'
    thumbnails = root / 'thumbnails'
    originals.mkdir(parents=True, exist_ok=True)
    thumbnails.mkdir(parents=True, exist_ok=True)
    unique = uuid.uuid4().hex
    final = originals / (unique + suffix)
    poster = thumbnails / (unique + '.jpg')
    committed = False

    def duplicate_response(row):
        return {
            'status': 'duplicate', 'id': row['id'],
            'in_trash': bool(row['deleted_at']),
            'existing': {key: row[key] for key in
                         ('id', 'original_filename', 'mime_type', 'media_type')},
        }

    try:
        # SHA-256 and filename checks run BEFORE ffprobe / FFmpeg.
        with database(get_connection) as (conn, cursor):
            cursor.execute('''SELECT id,original_filename,mime_type,media_type,deleted_at
                FROM photos WHERE user_id=%s AND sha256=%s LIMIT 1''', (uid, sha256))
            existing = cursor.fetchone()
            if existing:
                return duplicate_response(existing)
            if on_duplicate == 'skip':
                conflict = find_filename_collision(cursor, uid, name, sha256)
                if conflict:
                    return filename_collision_response(conflict)

        width, height, duration_ms = _probe(staging, suffix)
        _poster(staging, poster)

        with database(get_connection) as (conn, cursor):
            cursor.execute('SELECT storage_quota_bytes,is_active FROM users WHERE id=%s FOR UPDATE', (uid,))
            account = cursor.fetchone()
            if not account or not account['is_active']:
                raise HTTPException(403, 'Account unavailable')
            cursor.execute('''SELECT id,original_filename,mime_type,media_type,deleted_at
                FROM photos WHERE user_id=%s AND sha256=%s LIMIT 1''', (uid, sha256))
            existing = cursor.fetchone()
            if existing:
                return duplicate_response(existing)
            if on_duplicate == 'skip':
                conflict = find_filename_collision(cursor, uid, name, sha256)
                if conflict:
                    return filename_collision_response(conflict)
            else:
                cursor.execute('SELECT id FROM photos WHERE user_id=%s AND original_filename=%s LIMIT 1', (uid, name))
                if cursor.fetchone():
                    raise HTTPException(409, 'That filename already exists; choose another name')
            cursor.execute('SELECT COALESCE(SUM(size_bytes + resource_bytes),0) AS used FROM photos WHERE user_id=%s', (uid,))
            used = int(cursor.fetchone()['used'] or 0)
            quota = account['storage_quota_bytes']
            if quota is not None and used + size > quota:
                raise HTTPException(507, 'Account storage quota exceeded')
            if shutil.disk_usage(originals).free < MIN_FREE_BYTES:
                raise HTTPException(507, 'Insufficient server disk space')
            staging.replace(final)
            cursor.execute('''INSERT INTO photos
                (user_id,original_filename,storage_path,thumbnail_path,mime_type,size_bytes,
                 width,height,sha256,media_type,duration_ms)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'video',%s)''',
                (uid, name, str(final), str(poster), VIDEO_EXTENSIONS[suffix][0],
                 size, width, height, sha256, duration_ms))
            new_id = cursor.lastrowid
            conn.commit()
            committed = True
        return {'status': 'uploaded', 'id': new_id, 'filename': name,
                'media_type': 'video', 'size_bytes': size}
    finally:
        if not committed:
            final.unlink(missing_ok=True)
            poster.unlink(missing_ok=True)

def _probe(path: Path, extension: str):
    """Do not trust upload MIME or extension as proof of valid video content."""
    try:
        process = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries',
             'format=format_name,duration:stream=codec_type,width,height',
             '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=35, check=True,
        )
        data = json.loads(process.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise HTTPException(415, 'Video could not be decoded or inspected') from exc
    container = data.get('format', {}).get('format_name', '')
    allowed = VIDEO_EXTENSIONS[extension][1]
    if not any(item in container.split(',') for item in allowed):
        raise HTTPException(415, 'The video container does not match its file extension')
    video = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not video:
        raise HTTPException(415, 'This file contains no video stream')
    try:
        duration = float(data.get('format', {}).get('duration') or 0)
    except (ValueError, TypeError):
        duration = 0
    return int(video.get('width') or 0), int(video.get('height') or 0), max(0, round(duration * 1000))


def _poster(source: Path, destination: Path):
    temp = destination.with_name(destination.name + '.tmp')
    try:
        # Extract a frame early to handle short clips and avoid a full transcode.
        command = ['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-y',
                   '-i', str(source), '-map', '0:v:0', '-frames:v', '1',
                   '-vf', 'scale=480:480:force_original_aspect_ratio=decrease',
                   '-q:v', '3', '-f', 'image2', str(temp)]
        subprocess.run(command, capture_output=True, timeout=45, check=True)
        if not temp.is_file() or temp.stat().st_size == 0:
            raise RuntimeError('No poster frame was generated')
        temp.replace(destination)
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        raise HTTPException(422, 'Unable to generate a thumbnail for this video') from exc
    finally:
        temp.unlink(missing_ok=True)


def build_video_router(get_connection, get_current_user):
    router = APIRouter(prefix='/api/videos', tags=['Videos'])

    def owned_video(user_id, photo_id):
        with database(get_connection) as (conn, cursor):
            cursor.execute('''SELECT id,user_id,storage_path,mime_type,original_filename,
                                  thumbnail_path,deleted_at
                              FROM photos WHERE id=%s AND user_id=%s AND media_type='video' ''',
                           (photo_id, user_id))
            photo = cursor.fetchone()
        if not photo or photo['deleted_at'] is not None:
            raise HTTPException(404, 'Video unavailable')
        file_path = Path(photo['storage_path']).resolve()
        account_root = (MEDIA_ROOT / 'users' / str(user_id) / 'originals').resolve()
        if not file_path.is_relative_to(account_root) or not file_path.is_file():
            raise HTTPException(404, 'Original video unavailable')
        return photo, file_path

    @router.post('/upload')
    def upload_video(file: UploadFile = File(...),
                     on_duplicate: str = Form('skip'),
                     new_name: str | None = Form(None),
                     user=Depends(get_current_user)):
        if on_duplicate not in ('skip', 'keep'):
            raise HTTPException(422, 'Invalid duplicate decision')
        uid = user['id']
        name = (file.filename or 'video').replace('\\', '/').split('/')[-1][:255]
        if Path(name).suffix.lower() not in VIDEO_EXTENSIONS:
            raise HTTPException(415, 'Supported videos: MP4, M4V, MOV, WebM and MKV')
        try:
            staging, size, sha256 = stage_video_file(file, uid)
            try:
                return save_staged_video(get_connection, user, staging, name, size, sha256,
                                         on_duplicate=on_duplicate, new_name=new_name)
            finally:
                staging.unlink(missing_ok=True)
        finally:
            file.file.close()

    @router.post('/{video_id}/playback-url')
    def playback_url(video_id: int, user=Depends(get_current_user)):
        owned_video(user['id'], video_id)
        token = jwt.encode({
            'sub': str(user['id']), 'video_id': video_id, 'scope': 'video-playback',
            'iss': 'locallens', 'aud': 'locallens-video',
            'exp': datetime.now(timezone.utc) + timedelta(hours=4),
        }, os.environ['JWT_SECRET'], algorithm='HS256')
        return {'url': f'/api/videos/{video_id}/stream?ticket={token}'}

    @router.get('/{video_id}/stream')
    def stream(video_id: int, ticket: str, download: bool = False):
        try:
            claims = jwt.decode(ticket, os.environ['JWT_SECRET'], algorithms=['HS256'],
                                issuer='locallens', audience='locallens-video')
            if claims.get('scope') != 'video-playback' or int(claims['video_id']) != video_id:
                raise ValueError('Invalid scope or video')
            uid = int(claims['sub'])
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(403, 'Playback link expired or invalid') from exc
        photo, path = owned_video(uid, video_id)
        return FileResponse(path, media_type=photo['mime_type'],
                            filename=photo['original_filename'] if download else None,
                            content_disposition_type='attachment' if download else 'inline',
                            headers={'Cache-Control':'private, no-store',
                                     'Referrer-Policy':'no-referrer',
                                     'X-Content-Type-Options':'nosniff'})

    return router
