"""Indexed, single-write motion pairing and one-time metadata inspection."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from photos import database
from videos import save_staged_video, VIDEO_MAX_BYTES
from motion_service import MAX_BYTES as MOTION_MAX_BYTES
from motion_service import (
    asset_identifier, attach_staged, stage_upload, validate_original_path,
)


class InspectRequest(BaseModel):
    photo_ids: list[int] = Field(default_factory=list, max_length=200)


def build_universal_media_router(get_connection, get_current_user):
    router = APIRouter(prefix='/api/media', tags=['Media import'])

    @router.post('/inspect')
    def inspect(data: InspectRequest, user=Depends(get_current_user)):
        ids = list(dict.fromkeys(n for n in data.photo_ids if type(n) is int and n > 0))
        if not ids:
            return {'items': []}
        placeholders = ','.join(['%s'] * len(ids))
        with database(get_connection) as (conn, cur):
            cur.execute(f'''SELECT p.id,p.storage_path,p.content_identifier,p.content_identifier_checked_at,
                EXISTS(SELECT 1 FROM photo_resources r
                       WHERE r.photo_id=p.id AND r.resource_type='live_video') AS has_motion
                FROM photos p WHERE p.user_id=%s AND p.id IN ({placeholders})''',
                (user['id'], *ids))
            rows = cur.fetchall()
        # Extract metadata only for photos which haven't yet been indexed.
        discoveries = []
        for photo in rows:
            identifier = photo['content_identifier']
            if not photo['content_identifier_checked_at'] and not photo['has_motion']:
                try:
                    path = validate_original_path(photo['storage_path'], user['id'])
                    identifier = asset_identifier(path)
                except HTTPException:
                    identifier = None
                discoveries.append((identifier, photo['id'], user['id']))
            photo['content_identifier'] = identifier
        if discoveries:
            with database(get_connection) as (conn, cur):
                cur.executemany('''UPDATE photos SET content_identifier=COALESCE(content_identifier,%s),
                    content_identifier_checked_at=UTC_TIMESTAMP()
                    WHERE id=%s AND user_id=%s AND content_identifier_checked_at IS NULL''', discoveries)
                conn.commit()
        return {'items': [
            {'id':row['id'], 'motion_attached':bool(row['has_motion']),
             'possible_motion_missing':bool(row['content_identifier'] and not row['has_motion'])}
            for row in rows
        ]}

    @router.post('/auto-motion')
    def auto_motion(
        file: UploadFile = File(...),
        candidate_photo_ids: str = Form('[]'),
        allow_standalone: bool = Form(False),
        user=Depends(get_current_user),
    ):
        name = (file.filename or '').replace('\\', '/').split('/')[-1][:255]
        if not name.lower().endswith('.mov'):
            raise HTTPException(415, 'Motion pairing requires an original MOV file')
        try:
            ids = json.loads(candidate_photo_ids)
            if (not isinstance(ids,list) or len(ids)>200 or
                any(type(n) is not int or n <= 0 for n in ids)):
                raise ValueError('Invalid candidate IDs')
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, 'Invalid candidate IDs') from exc
        try:
            temp,size,sha256,motion_id = stage_upload(file,user['id'],max_bytes=VIDEO_MAX_BYTES)
            try:
                with database(get_connection) as (conn,cur):
                    cur.execute('''SELECT p.id FROM photo_resources r
                        JOIN photos p ON p.id=r.photo_id
                        WHERE p.user_id=%s
                        AND r.resource_type='live_video' AND r.sha256=%s
                        LIMIT 1''', (user['id'],sha256))
                    already_paired = cur.fetchone()
                    if already_paired:
                        return {'status':'duplicate','id':already_paired['id'],'match_method':'hash'}
                    if motion_id:
                        cur.execute('''SELECT p.id FROM photos p
                            WHERE p.user_id=%s AND p.content_identifier=%s
                            AND p.deleted_at IS NULL
                            LIMIT 2''', (user['id'],motion_id))
                        matches = [row['id'] for row in cur.fetchall()]
                        if len(matches) > 1 and ids:
                            # Query batch candidates explicitly: they need not
                            # be among the first two historical matches.
                            targeted_ids = list(dict.fromkeys(ids))
                            marks = ','.join(['%s'] * len(targeted_ids))
                            cur.execute(f'''SELECT p.id FROM photos p
                                WHERE p.user_id=%s AND p.content_identifier=%s
                                AND p.deleted_at IS NULL
                                AND p.id IN ({marks})
                                AND NOT EXISTS(SELECT 1 FROM photo_resources r
                                    WHERE r.photo_id=p.id AND r.resource_type='live_video')''',
                                (user['id'],motion_id,*targeted_ids))
                            preferred = [row['id'] for row in cur.fetchall()]
                            if len(preferred) == 1:
                                matches = preferred
                    else:
                        # No identifier: only exactly one candidate from the selected folder,
                        # confirmed by matching basename and missing still identifier.
                        matches = []
                        candidate_ids = list(set(ids))
                        if candidate_ids:
                            marks = ','.join(['%s']*len(candidate_ids))
                            cur.execute(f'''SELECT id,storage_path,original_filename,content_identifier,content_identifier_checked_at
                                FROM photos WHERE user_id=%s AND deleted_at IS NULL
                                AND id IN ({marks})''', (user['id'],*candidate_ids))
                            candidates = cur.fetchall()
                        else:
                            candidates = []
                        for photo in candidates:
                            if Path(photo['original_filename']).stem.casefold() != Path(name).stem.casefold():
                                continue
                            identifier = photo['content_identifier']
                            if not identifier and not photo['content_identifier_checked_at']:
                                try:
                                    identifier = asset_identifier(validate_original_path(photo['storage_path'],user['id']))
                                except HTTPException:
                                    continue
                                cur.execute('''UPDATE photos SET content_identifier=%s,
                                    content_identifier_checked_at=UTC_TIMESTAMP()
                                    WHERE id=%s AND user_id=%s AND content_identifier_checked_at IS NULL''',
                                    (identifier,photo['id'],user['id']))
                                conn.commit()
                            if not identifier:
                                matches.append(photo['id'])
                if len(matches) > 1:
                    raise HTTPException(409, 'Multiple photos match this motion file; pairing is ambiguous')
                if not matches:
                    # Preserve motion originals whose embedded identifier is known.
                    # They may be part of an incomplete Live Photo backup.
                    if allow_standalone and not motion_id:
                        return save_staged_video(get_connection, user, temp, name, size, sha256)
                    return {'status': 'unmatched', 'reason':
                            'motion_identifier_without_still' if motion_id else 'no_matching_still'}
                if size > MOTION_MAX_BYTES:
                    raise HTTPException(413, 'Live Photo motion exceeds the configured size limit')
                return attach_staged(
                    get_connection,user,matches[0],temp,name,size,sha256,motion_id,
                    allow_filename=not bool(motion_id),
                )
            finally:
                temp.unlink(missing_ok=True)
        finally:
            file.file.close()

    return router
