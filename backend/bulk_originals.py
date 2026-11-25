"""Lossless, account-scoped multi-original ZIP downloads for LocalLens.

POST /api/media/bulk-prepare (Bearer authentication) -> one-time, short-lived URL.
GET /api/media/bulk-download/{ticket} -> ZIP via native browser download.
The browser never needs to construct a giant in-memory Blob.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote
import hashlib
import json
import os
import secrets
import time
import shutil
import tempfile
import zipfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from photos import database

MAX_ITEMS = 100
MAX_TOTAL_BYTES = 12 * 1024**3
RESERVE_BYTES = int(os.getenv('MIN_FREE_DISK_GB', '10')) * 1024**3
MEDIA_ROOT = Path(os.getenv('MEDIA_ROOT', '/storage')).resolve()


class BulkRequest(BaseModel):
    photo_ids: list[int] = Field(min_length=1, max_length=MAX_ITEMS)


def _unique_photo_ids(ids):
    if any(type(n) is not int or n <= 0 for n in ids):
        raise HTTPException(422, 'Invalid photo ID')
    unique = list(dict.fromkeys(ids))
    if len(unique) > MAX_ITEMS:
        raise HTTPException(413, 'Select at most 100 items per download')
    return unique


def _owner_file(uid: int, recorded: str, kind: str):
    root = MEDIA_ROOT / 'users' / str(uid) / kind
    path = Path(recorded).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise HTTPException(404, 'An original file is unavailable in this account')
    return path


def _safe_name(raw: str, default: str):
    name = str(raw or '').replace('\\', '/').split('/')[-1].strip()
    if not name or name in ('.', '..') or '\x00' in name:
        return default
    # Keep original names where possible, protect against ZIP path traversal.
    return name[:240]


def _rows(cur, uid: int, photo_ids: list[int]):
    marks = ','.join(['%s'] * len(photo_ids))
    cur.execute(f'''SELECT p.id,p.user_id,p.storage_path,p.original_filename,
                  p.size_bytes, r.storage_path AS motion_path,
                  r.original_filename AS motion_filename,r.size_bytes AS motion_size
          FROM photos p
          LEFT JOIN photo_resources r
            ON r.photo_id=p.id AND r.resource_type='live_video'
          WHERE p.user_id=%s AND p.deleted_at IS NULL
            AND p.id IN ({marks})''', (uid, *photo_ids))
    fetched = cur.fetchall()
    keyed = {}
    for row in fetched:
        if row['id'] in keyed:
            raise HTTPException(409, 'Duplicate Live Photo resources found')
        keyed[row['id']] = row
    if len(keyed) != len(photo_ids):
        raise HTTPException(404, 'One or more selected photos are missing or inaccessible')
    return [keyed[n] for n in photo_ids]


def _files_for_rows(uid, rows):
    result = []
    size = 0
    for row in rows:
        original = _owner_file(uid, row['storage_path'], 'originals')
        contents = [(original, _safe_name(row['original_filename'], f'original-{row["id"]}'), 'originals')]
        if row.get('motion_path'):
            motion = _owner_file(uid, row['motion_path'], 'resources')
            motion_name = _safe_name(row['motion_filename'], f'motion-{row["id"]}.mov')
            if motion_name.casefold() == contents[0][1].casefold():
                motion_name = 'motion-' + motion_name
            contents.append((motion, motion_name, 'resources'))
        size += sum(path.stat().st_size for path, _, _ in contents)
        if size > MAX_TOTAL_BYTES:
            raise HTTPException(413, 'Selected originals exceed the 12 GiB ZIP limit; use smaller selections')
        result.append((row['id'], contents))
    return result, size


def _prune_stale_archives(folder: Path):
    # A crash during streaming can leave a temporary ZIP behind.
    cutoff = time.time() - 24 * 3600
    for file in folder.glob('.bulk-originals-*.zip'):
        try:
            if file.is_file() and file.stat().st_mtime < cutoff:
                file.unlink()
        except OSError:
            pass


def build_bulk_originals_router(get_connection, get_current_user):
    router = APIRouter(prefix='/api/media', tags=['Original media downloads'])

    @router.post('/bulk-prepare')
    def prepare(data: BulkRequest, user=Depends(get_current_user)):
        uid = int(user['id'])
        ids = _unique_photo_ids(data.photo_ids)
        with database(get_connection) as (conn, cur):
            rows = _rows(cur, uid, ids)
            _files_for_rows(uid, rows)  # Fail early, before issuing a ticket.
            ticket = secrets.token_urlsafe(32)
            digest = hashlib.sha256(ticket.encode('ascii')).hexdigest()
            cur.execute('''INSERT INTO media_bulk_download_tokens
                 (token_digest,user_id,photo_ids,expires_at)
                 VALUES (%s,%s,%s,DATE_ADD(NOW(6), INTERVAL 10 MINUTE))''',
                (digest, uid, json.dumps(ids)))
            cur.execute('DELETE FROM media_bulk_download_tokens WHERE expires_at < DATE_SUB(NOW(6), INTERVAL 1 DAY)')
            conn.commit()
        return {'url': '/api/media/bulk-download/' + quote(ticket), 'expires_in': 600,
                'count': len(ids)}

    @router.get('/bulk-download/{ticket}')
    def download(ticket: str):
        if len(ticket) > 128 or not ticket.isascii():
            raise HTTPException(404, 'Download link unavailable')
        digest = hashlib.sha256(ticket.encode('ascii')).hexdigest()
        with database(get_connection) as (conn, cur):
            cur.execute('''SELECT token_digest,user_id,photo_ids FROM media_bulk_download_tokens
               WHERE token_digest=%s AND used_at IS NULL AND expires_at > NOW(6)
               FOR UPDATE''', (digest,))
            token_row = cur.fetchone()
            if not token_row:
                raise HTTPException(404, 'Download link expired or already used')
            uid = int(token_row['user_id'])
            cur.execute('SELECT is_active FROM users WHERE id=%s', (uid,))
            account = cur.fetchone()
            if not account or not account['is_active']:
                raise HTTPException(403, 'Account is no longer active')
            raw_ids = token_row['photo_ids']
            if isinstance(raw_ids, (str, bytes, bytearray)):
                raw_ids = json.loads(raw_ids)
            ids = _unique_photo_ids(raw_ids)
            rows = _rows(cur, uid, ids)  # Re-validate ownership and trash state at download time.
            files, raw_size = _files_for_rows(uid, rows)
            cur.execute('UPDATE media_bulk_download_tokens SET used_at=NOW(6) WHERE token_digest=%s', (digest,))
            conn.commit()
        folder = MEDIA_ROOT / 'users' / str(uid) / 'bundles'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        _prune_stale_archives(folder)
        if shutil.disk_usage(folder).free < RESERVE_BYTES + raw_size + 1024 * 1024:
            raise HTTPException(507, 'Not enough free storage to prepare ZIP archive')
        fd, output_name = tempfile.mkstemp(prefix='.bulk-originals-', suffix='.zip', dir=folder)
        os.close(fd)
        output = Path(output_name)
        try:
            # Revalidate paths immediately before reading. Folder prefix is per-user.
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                for pid, media in files:
                    for path, filename, kind in media:
                        _owner_file(uid, str(path), kind)
                        archive.write(path, arcname=f'photo-{pid}/{filename}')
            return FileResponse(output, media_type='application/zip',
                filename=f'LocalLens-{len(files)}-originals.zip',
                content_disposition_type='attachment',
                headers={'Cache-Control':'private, no-store', 'Referrer-Policy':'no-referrer',
                         'X-Content-Type-Options':'nosniff'},
                background=BackgroundTask(output.unlink, missing_ok=True))
        except Exception:
            output.unlink(missing_ok=True)
            raise

    return router
