"""Small authenticated SHA-256 lookup before sending original media bytes.

This is only an optimization: upload handlers MUST still verify actual received
bytes and perform their existing duplicate and quota checks.
"""
import re

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from guard import database


class DuplicateLookup(BaseModel):
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(gt=0, le=10 * 1024**3)


class PhotoSizes(BaseModel):
    sizes: list[int] = Field(min_length=1, max_length=300)


class BatchDuplicateItem(BaseModel):
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(gt=0, le=10 * 1024**3)


class BatchDuplicateLookup(BaseModel):
    items: list[BatchDuplicateItem] = Field(min_length=1, max_length=200)


class ImportReceiptLookup(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


def build_duplicate_preflight_router(get_connection, get_current_user):
    router = APIRouter(prefix='/api/media', tags=['Media'])

    @router.post('/check-duplicate')
    def check_duplicate(body: DuplicateLookup, user=Depends(get_current_user)):
        digest = body.sha256.lower()
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            from fastapi import HTTPException
            raise HTTPException(422, 'Invalid SHA-256 checksum')
        with database(get_connection) as (conn, cur):
            cur.execute('''SELECT id,media_type,deleted_at FROM photos
                WHERE user_id=%s AND sha256=%s AND size_bytes=%s LIMIT 1''',
                (user['id'], digest, body.size_bytes))
            found = cur.fetchone()
            if found:
                return {'status':'duplicate', 'id':found['id'],
                        'kind':found['media_type'], 'in_trash':bool(found['deleted_at'])}
            # Live Photo MOV originals are resource records, not independent videos.
            # Matching the complete SHA-256 is authoritative even if a name changed.
            cur.execute('''SELECT p.id,p.deleted_at FROM photo_resources r
                JOIN photos p ON p.id=r.photo_id
                WHERE p.user_id=%s AND r.resource_type='live_video' AND r.sha256=%s
                LIMIT 1''', (user['id'], digest))
            found = cur.fetchone()
            if found:
                return {'status':'duplicate', 'id':found['id'],
                        'kind':'live_video', 'in_trash':bool(found['deleted_at'])}
        return {'status':'new'}

    @router.post('/check-photo-sizes')
    def photo_sizes(body: PhotoSizes, user=Depends(get_current_user)):
        # Match by byte length, not name: renamed duplicates remain detectable.
        sizes = list(dict.fromkeys(body.sizes))
        if any(type(n) is not int or n <= 0 or n > 10 * 1024**3 for n in sizes):
            from fastapi import HTTPException
            raise HTTPException(422, 'Invalid photo sizes')
        marks = ','.join(['%s'] * len(sizes))
        with database(get_connection) as (_, cur):
            cur.execute(f"SELECT DISTINCT size_bytes FROM photos WHERE user_id=%s AND size_bytes IN ({marks})",
                        (user['id'], *sizes))
            return {'sizes': [row['size_bytes'] for row in cur.fetchall()]}

    @router.post('/check-duplicates-batch')
    def check_duplicates_batch(body: BatchDuplicateLookup, user=Depends(get_current_user)):
        """Exact server-side checksums; return order matches input order."""
        requested = [(item.sha256.lower(), item.size_bytes) for item in body.items]
        if any(not re.fullmatch(r'[0-9a-f]{64}', digest) for digest, _ in requested):
            from fastapi import HTTPException
            raise HTTPException(422, 'Invalid SHA-256 checksum')
        digests = list(dict.fromkeys(digest for digest, _ in requested))
        marks = ','.join(['%s'] * len(digests))
        found = {}
        with database(get_connection) as (_, cur):
            cur.execute(f'''SELECT id, media_type, deleted_at, sha256, size_bytes
                FROM photos WHERE user_id=%s AND sha256 IN ({marks})''',
                (user['id'], *digests))
            for row in cur.fetchall():
                found[(row['sha256'].lower(), row['size_bytes'])] = {
                    'status': 'duplicate', 'id': row['id'],
                    'kind': row['media_type'], 'in_trash': bool(row['deleted_at'])}
            cur.execute(f'''SELECT p.id, p.deleted_at, r.sha256, r.size_bytes
                FROM photo_resources r JOIN photos p ON p.id=r.photo_id
                WHERE p.user_id=%s AND r.resource_type='live_video'
                  AND r.sha256 IN ({marks})''', (user['id'], *digests))
            for row in cur.fetchall():
                found.setdefault((row['sha256'].lower(), row['size_bytes']), {
                    'status': 'duplicate', 'id': row['id'],
                    'kind': 'live_video', 'in_trash': bool(row['deleted_at'])})
        return {'results': [found.get(key, {'status': 'new'}) for key in requested]}

    @router.post('/import-receipts')
    def import_receipts(body: ImportReceiptLookup, user=Depends(get_current_user)):
        """Only reveal original hashes owned by the requesting account."""
        ids = list(dict.fromkeys(body.ids))
        if any(type(pid) is not int or pid < 1 for pid in ids):
            from fastapi import HTTPException
            raise HTTPException(422, 'Invalid media IDs')
        marks = ','.join(['%s'] * len(ids))
        entries = []
        with database(get_connection) as (_, cur):
            cur.execute(f'''SELECT id, media_type, sha256, size_bytes FROM photos
                WHERE user_id=%s AND deleted_at IS NULL AND id IN ({marks})''',
                (user['id'], *ids))
            for row in cur.fetchall():
                entries.append({'id': row['id'],
                    'kind': 'video' if row['media_type'] == 'video' else 'photo',
                    'sha256': row['sha256'], 'size_bytes': row['size_bytes']})
            cur.execute(f'''SELECT p.id, r.sha256, r.size_bytes FROM photo_resources r
                JOIN photos p ON p.id=r.photo_id WHERE p.user_id=%s
                  AND p.deleted_at IS NULL AND r.resource_type='live_video'
                  AND p.id IN ({marks})''', (user['id'], *ids))
            for row in cur.fetchall():
                entries.append({'id': row['id'], 'kind': 'live_video',
                    'sha256': row['sha256'], 'size_bytes': row['size_bytes']})
        return {'entries': entries}


    @router.get('/library-count')
    def library_count(media: str = Query('photo', pattern='^(photo|video|all)$'),
                      favorite: bool = False, trash: bool = False, search: str = '',
                      user=Depends(get_current_user)):
        conditions = ['user_id=%s', 'deleted_at IS NOT NULL' if trash else 'deleted_at IS NULL']
        parameters = [user['id']]
        if media == 'photo':
            conditions.append("(media_type <> 'video' OR media_type IS NULL)")
        elif media == 'video':
            conditions.append("media_type = 'video'")
        if favorite:
            conditions.append('is_favorite=1')
        if search:
            conditions.append('original_filename LIKE %s')
            parameters.append('%' + search[:200] + '%')
        sql = 'SELECT COUNT(*) AS total FROM photos WHERE ' + ' AND '.join(conditions)
        with database(get_connection) as (_, cur):
            cur.execute(sql, tuple(parameters))
            return {'total': int(cur.fetchone()['total'])}

    return router
