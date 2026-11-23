"""Shared, single-write attachment of a validated motion original.

Called by both automatic pairing and the legacy explicit attachment endpoint.
Never transcodes the uploaded original.
"""
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import HTTPException
from photos import database

ROOT = Path(os.getenv('MEDIA_ROOT', '/storage')).resolve()
MAX_BYTES = int(os.getenv('MAX_UPLOAD_MB', '100')) * 1024**2
MIN_FREE_BYTES = int(os.getenv('MIN_FREE_DISK_GB', '10')) * 1024**3


def asset_identifier(path):
    try:
        result = subprocess.run(
            ['exiftool', '-j', '-G1', '-ContentIdentifier', '-MediaGroupUUID', str(path)],
            capture_output=True, text=True, check=True, timeout=25,
        )
        rows = json.loads(result.stdout)
        if not rows:
            return None
        for key, value in rows[0].items():
            if key.rsplit(':', 1)[-1].lower() in ('contentidentifier', 'mediagroupuuid') and value:
                return str(value).strip().lower()
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return None


def validate_original_path(value, user_id):
    root = (ROOT / 'users' / str(user_id) / 'originals').resolve()
    path = Path(value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, 'Original image is unavailable')
    return path


def stage_upload(upload, user_id, *, max_bytes=MAX_BYTES):
    """Stream the incoming MOV to disk once; compute the hash in that pass."""
    folder = (ROOT / 'users' / str(user_id) / 'resources').resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(folder).free < MIN_FREE_BYTES + 1024 * 1024:
        raise HTTPException(507, 'Insufficient server storage')
    temp = folder / (uuid.uuid4().hex + '.upload.mov')
    digest = hashlib.sha256()
    size = 0
    try:
        with temp.open('xb') as handle:
            while True:
                chunk = upload.file.read(1024**2)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, 'Motion file exceeds the upload limit')
                if shutil.disk_usage(folder).free < MIN_FREE_BYTES + len(chunk):
                    raise HTTPException(507, 'Insufficient server storage')
                digest.update(chunk)
                handle.write(chunk)
        if not size:
            raise HTTPException(415, 'Empty motion file')
        return temp, size, digest.hexdigest(), asset_identifier(temp)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def motion_duration_ms(path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        info = json.loads(result.stdout)
        if not any(stream.get('codec_type') == 'video' for stream in info.get('streams', [])):
            raise HTTPException(415, 'MOV file has no video stream')
        duration = float(info.get('format', {}).get('duration') or 0)
        if not (0 < duration <= 30):
            raise HTTPException(422, 'Motion clip must be between 0 and 30 seconds')
        return round(duration * 1000)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(422, 'Unable to inspect motion video') from exc


def attach_staged(get_connection, user, photo_id, temp, name, size, sha256, motion_id, *, allow_filename=False):
    """Validate pairing and persist a staged original once. Caller owns temp cleanup."""
    uid = user['id']
    duration_ms = motion_duration_ms(temp)
    final = temp.parent / (uuid.uuid4().hex + '.mov')
    committed = False
    try:
        with database(get_connection) as (conn, cur):
            # The per-user row lock protects quota calculation against concurrent uploads.
            cur.execute('SELECT storage_quota_bytes,is_active FROM users WHERE id=%s FOR UPDATE', (uid,))
            account = cur.fetchone()
            if not account or not account['is_active']:
                raise HTTPException(403, 'Account unavailable')
            cur.execute('''SELECT id,storage_path,original_filename,content_identifier,content_identifier_checked_at
                FROM photos WHERE id=%s AND user_id=%s AND deleted_at IS NULL FOR UPDATE''', (photo_id,uid))
            photo = cur.fetchone()
            if not photo:
                raise HTTPException(404, 'Photo not found or is in trash')
            still = validate_original_path(photo['storage_path'], uid)
            still_id = photo['content_identifier']
            # Older imports do not necessarily have the identifier indexed yet.
            if not still_id and not photo['content_identifier_checked_at']:
                still_id = asset_identifier(still)
                cur.execute('''UPDATE photos SET content_identifier=%s,
                    content_identifier_checked_at=UTC_TIMESTAMP() WHERE id=%s''', (still_id,photo_id))

            if still_id or motion_id:
                if not still_id or not motion_id or still_id != motion_id:
                    raise HTTPException(422, 'Still and motion content identifiers do not match')
                method = 'identifier'
            else:
                if not allow_filename or Path(name).stem.casefold() != Path(photo['original_filename']).stem.casefold():
                    raise HTTPException(422, 'A verified matching still image was not found')
                method = 'filename'

            cur.execute("SELECT sha256 FROM photo_resources WHERE photo_id=%s AND resource_type='live_video' LIMIT 1", (photo_id,))
            previous = cur.fetchone()
            if previous:
                if previous['sha256'] == sha256:
                    conn.commit()
                    return {'status':'duplicate', 'id':photo_id, 'match_method':method}
                raise HTTPException(409, 'This photograph already has a different motion original')

            cur.execute('SELECT COALESCE(SUM(size_bytes + resource_bytes),0) AS used FROM photos WHERE user_id=%s', (uid,))
            used = int(cur.fetchone()['used'])
            quota = account['storage_quota_bytes']
            if quota is not None and used + size > quota:
                raise HTTPException(507, 'Storage quota exceeded')
            if shutil.disk_usage(temp.parent).free < MIN_FREE_BYTES:
                raise HTTPException(507, 'Insufficient server storage')
            temp.replace(final)
            cur.execute('''INSERT INTO photo_resources
                (photo_id,resource_type,original_filename,storage_path,mime_type,size_bytes,sha256,content_identifier,duration_ms)
                VALUES(%s,'live_video',%s,%s,'video/quicktime',%s,%s,%s,%s)''',
                (photo_id,name,str(final),size,sha256,still_id or motion_id,duration_ms))
            cur.execute("UPDATE photos SET media_type='live_photo',resource_bytes=resource_bytes+%s WHERE id=%s", (size,photo_id))
            conn.commit()
            committed = True
        return {'status':'attached', 'id':photo_id, 'match_method':method}
    finally:
        if not committed:
            final.unlink(missing_ok=True)
