"""LocalLens AI automatic indexing controls, activity leases, and viewer labels.

All face and pet endpoints are account-scoped; no cross-account results.
"""
import asyncio
import logging
import time
import uuid
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

LOG = logging.getLogger('uvicorn.error')

@contextmanager
def db(get_connection):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        yield conn, cur
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def update_activity(get_connection, kind, request_id=None):
    """Short database write run in a thread when called from ASGI middleware."""
    with db(get_connection) as (conn, cur):
        if kind == 'browse':
            cur.execute('UPDATE ai_index_activity SET last_browse_at=NOW(6) WHERE id=1')
        elif kind == 'upload_started':
            cur.execute('''INSERT INTO ai_upload_leases(request_id,heartbeat_at)
                           VALUES (%s,NOW(6)) ON DUPLICATE KEY UPDATE heartbeat_at=NOW(6)''', (request_id,))
            cur.execute('UPDATE ai_index_activity SET last_upload_at=NOW(6) WHERE id=1')
        elif kind == 'upload_heartbeat':
            cur.execute('UPDATE ai_upload_leases SET heartbeat_at=NOW(6) WHERE request_id=%s', (request_id,))
        elif kind == 'upload_finished':
            cur.execute('DELETE FROM ai_upload_leases WHERE request_id=%s', (request_id,))
            cur.execute('UPDATE ai_index_activity SET last_upload_at=NOW(6) WHERE id=1')
        conn.commit()


class AiActivityMiddleware:
    """Count overlapping media requests instead of treating gestures as load.

    A pressure pulse is an asynchronous, rate-limited database update so it
    never holds up a frontend response. Upload leases remain fully enabled.
    """
    _active_views = 0
    _last_pressure = 0.0
    _concurrency_limit = 7

    def __init__(self, app, get_connection):
        self.app = app
        self.get_connection = get_connection

    async def _mark(self, kind, rid=None):
        try:
            await asyncio.to_thread(update_activity, self.get_connection, kind, rid)
        except Exception as exc:
            LOG.warning('Smart Library activity tracking unavailable: %s', type(exc).__name__)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope.get('path', '')
        method = scope.get('method', '')
        is_upload = method in ('POST', 'PUT', 'PATCH') and (
            ('upload' in path or 'import' in path) and path.startswith('/api/'))
        is_view = method == 'GET' and (
            path.startswith('/api/photos') or path.startswith('/api/albums')
            or path.startswith('/api/media') or path.startswith('/api/shared'))
        if is_view:
            cls = type(self)
            cls._active_views += 1
            now = time.monotonic()
            if cls._active_views >= cls._concurrency_limit and now - cls._last_pressure >= 3:
                cls._last_pressure = now
                asyncio.create_task(self._mark('browse'))  # high demand, not browsing
            try:
                return await self.app(scope, receive, send)
            finally:
                cls._active_views = max(0,cls._active_views - 1)
        if not is_upload:
            return await self.app(scope, receive, send)
        rid = str(uuid.uuid4())
        await self._mark('upload_started', rid)
        active = True

        async def heartbeat():
            while active:
                await asyncio.sleep(12)
                if active:
                    await self._mark('upload_heartbeat', rid)

        task = asyncio.create_task(heartbeat())
        try:
            return await self.app(scope, receive, send)
        finally:
            active = False
            task.cancel()
            await self._mark('upload_finished', rid)


class AutoControl(BaseModel):
    auto_enabled: bool


class PetLabel(BaseModel):
    name: str = Field(min_length=1, max_length=100)


def build_auto_router(get_connection, get_current_user):
    router = APIRouter(prefix='/api/ai', tags=['AI automation'])

    @router.post('/activity')
    def activity(user=Depends(get_current_user)):
        # Compatibility endpoint. Gestures never pause photo analysis.
        return {'ok': True}

    @router.get('/automation/status')
    def status(user=Depends(get_current_user)):
        uid = user['id']
        with db(get_connection) as (_,cur):
            cur.execute('SELECT auto_enabled FROM ai_index_control WHERE user_id=%s', (uid,))
            auto = bool((cur.fetchone() or {}).get('auto_enabled'))
            cur.execute('''SELECT TIMESTAMPDIFF(SECOND,last_browse_at,NOW()) browse_age,
                                  TIMESTAMPDIFF(SECOND,last_upload_at,NOW()) upload_age
                           FROM ai_index_activity WHERE id=1''')
            active = cur.fetchone() or {}
            cur.execute('''SELECT COUNT(*) count FROM ai_upload_leases
                           WHERE heartbeat_at > DATE_SUB(NOW(6), INTERVAL 45 SECOND)''')
            uploads = cur.fetchone()['count']
            cur.execute('''SELECT TIMESTAMPDIFF(SECOND,last_seen_at,NOW()) age
                           FROM ai_scheduler_heartbeat WHERE id=1''')
            online_age = (cur.fetchone() or {}).get('age')
            cur.execute('SELECT enabled FROM ai_face_settings WHERE user_id=%s', (uid,))
            faces_enabled = bool((cur.fetchone() or {}).get('enabled'))
            cur.execute('SELECT state,detail,updated_at FROM ai_face_model_health WHERE id=1')
            model_health = cur.fetchone() or {'state':'not_tested','detail':None}
            cur.execute('SELECT COUNT(*) count FROM ai_faces WHERE user_id=%s', (uid,))
            faces = cur.fetchone()['count']
            cur.execute('''SELECT COUNT(*) count FROM ai_faces
                           WHERE user_id=%s AND assignment_source='automatic'
                           AND person_id IS NOT NULL''', (uid,))
            auto_named_faces = cur.fetchone()['count']
            cur.execute('''SELECT COUNT(*) count FROM ai_faces f
                           LEFT JOIN ai_face_reviews r ON r.face_id=f.id AND r.user_id=f.user_id
                           WHERE f.user_id=%s AND f.person_id IS NULL AND r.face_id IS NULL''', (uid,))
            pending = cur.fetchone()['count']
            cur.execute('SELECT COUNT(*) count FROM ai_scans WHERE user_id=%s AND faces_done=1 AND error_message IS NULL', (uid,))
            face_scanned = cur.fetchone()['count']
            cur.execute('SELECT COUNT(*) count FROM ai_index_failures WHERE user_id=%s', (uid,))
            failures = cur.fetchone()['count']
            cur.execute('''SELECT COUNT(*) count FROM ai_scans
                           WHERE user_id=%s AND error_message IS NOT NULL''', (uid,))
            legacy_failures = cur.fetchone()['count']
            cur.execute('''SELECT COUNT(*) count FROM photos p
                           LEFT JOIN ai_scans s ON s.photo_id=p.id
                           WHERE p.user_id=%s AND p.deleted_at IS NULL
                           AND COALESCE(p.media_type,'photo')<>'video'
                           AND (s.photo_id IS NULL OR s.tags_done=0 OR
                               (%s=1 AND s.faces_done=0))''', (uid,int(faces_enabled)))
            remaining = cur.fetchone()['count']
        cause = None
        if uploads: cause = 'uploading'
        elif active.get('upload_age') is not None and active['upload_age'] < 12: cause = 'recent_upload'
        elif active.get('browse_age') is not None and active['browse_age'] < 12: cause = 'high_demand'
        return {'auto_enabled': auto, 'scheduler_online': online_age is not None and 0 <= online_age < 45,
                'idle_reason': cause, 'remaining': remaining, 'failed_photos': max(failures,legacy_failures),
                'faces_enabled': faces_enabled, 'faces_detected': faces, 'auto_named_faces': auto_named_faces, 'faces_pending': pending,
                'photos_face_scanned': face_scanned, 'face_model': model_health}

    @router.put('/automation/control')
    def control(payload:AutoControl, user=Depends(get_current_user)):
        with db(get_connection) as (conn,cur):
            cur.execute('''INSERT INTO ai_index_control(user_id,auto_enabled)
              VALUES (%s,%s) ON DUPLICATE KEY UPDATE auto_enabled=VALUES(auto_enabled)''',
              (user['id'], int(payload.auto_enabled)))
            conn.commit()
        return {'auto_enabled': payload.auto_enabled}

    @router.post('/automation/retry-failed')
    def retry_failed(user=Depends(get_current_user)):
        uid=user['id']
        with db(get_connection) as (conn,cur):
            cur.execute('''UPDATE ai_scans s
               LEFT JOIN ai_index_failures f ON f.photo_id=s.photo_id AND f.user_id=s.user_id
               SET s.tags_done=0,s.faces_done=0,s.error_message=NULL
               WHERE s.user_id=%s AND (f.photo_id IS NOT NULL OR s.error_message IS NOT NULL)''', (uid,))
            affected=cur.rowcount
            cur.execute('DELETE FROM ai_index_failures WHERE user_id=%s', (uid,))
            conn.commit()
        return {'queued': affected}

    @router.post('/automation/rescan-faces')
    def rescan_faces(user=Depends(get_current_user)):
        uid=user['id']
        with db(get_connection) as (conn,cur):
            cur.execute('SELECT enabled FROM ai_face_settings WHERE user_id=%s', (uid,))
            if not bool((cur.fetchone() or {}).get('enabled')):
                raise HTTPException(409,'Enable private facial recognition first')
            cur.execute('UPDATE ai_scans SET faces_done=0 WHERE user_id=%s', (uid,))
            affected=cur.rowcount
            conn.commit()
        return {'queued': affected}

    @router.get('/photo/{photo_id}/labels')
    def photo_labels(photo_id:int, user=Depends(get_current_user)):
        uid=user['id']
        with db(get_connection) as (_,cur):
            cur.execute('SELECT id FROM photos WHERE id=%s AND user_id=%s AND deleted_at IS NULL', (photo_id,uid))
            if not cur.fetchone(): raise HTTPException(404,'Photo not found')
            cur.execute('''SELECT f.id,f.x,f.y,f.w,f.h,f.person_id,f.assignment_source,
                                  p.display_name,f.suggested_person_id,s.display_name suggested_name
                           FROM ai_faces f LEFT JOIN ai_people p
                             ON p.id=f.person_id AND p.user_id=f.user_id
                           LEFT JOIN ai_people s
                             ON s.id=f.suggested_person_id AND s.user_id=f.user_id
                           WHERE f.photo_id=%s AND f.user_id=%s ORDER BY f.x''', (photo_id,uid))
            faces=cur.fetchall()
            cur.execute('''SELECT id,display_name FROM ai_pet_labels
                           WHERE photo_id=%s AND user_id=%s ORDER BY id''', (photo_id,uid))
            pets=cur.fetchall()
        return {'faces':faces,'pets':pets}

    @router.post('/photo/{photo_id}/pets')
    def add_pet(photo_id:int, payload:PetLabel, user=Depends(get_current_user)):
        name=payload.name.strip()
        if not name: raise HTTPException(422,'Name required')
        uid=user['id']
        with db(get_connection) as (conn,cur):
            cur.execute('SELECT id FROM photos WHERE id=%s AND user_id=%s AND deleted_at IS NULL', (photo_id,uid))
            if not cur.fetchone(): raise HTTPException(404,'Photo not found')
            cur.execute('''INSERT INTO ai_pet_labels(photo_id,user_id,display_name)
              VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)''', (photo_id,uid,name))
            label_id=cur.lastrowid
            conn.commit()
        return {'id':label_id,'name':name}

    @router.patch('/pet-labels/{label_id}')
    def rename_pet(label_id:int, payload:PetLabel, user=Depends(get_current_user)):
        name=payload.name.strip()
        if not name: raise HTTPException(422,'Name required')
        with db(get_connection) as (conn,cur):
            cur.execute('UPDATE ai_pet_labels SET display_name=%s WHERE id=%s AND user_id=%s',
                        (name,label_id,user['id']))
            if not cur.rowcount:
                cur.execute('SELECT 1 FROM ai_pet_labels WHERE id=%s AND user_id=%s', (label_id,user['id']))
                if not cur.fetchone(): raise HTTPException(404,'Pet label not found')
            conn.commit()
        return {'id':label_id,'name':name}

    @router.delete('/pet-labels/{label_id}')
    def remove_pet(label_id:int, user=Depends(get_current_user)):
        with db(get_connection) as (conn,cur):
            cur.execute('DELETE FROM ai_pet_labels WHERE id=%s AND user_id=%s', (label_id,user['id']))
            if not cur.rowcount: raise HTTPException(404,'Pet label not found')
            conn.commit()
        return {'deleted':True}

    @router.get('/automation/pet-candidates')
    def pet_candidates(limit:int=60, user=Depends(get_current_user)):
        # This is a coarse species-classification shortlist, NOT individual
        # animal recognition. Return only photos owned by the current user.
        limit=max(1,min(limit,100))
        with db(get_connection) as (_,cur):
            cur.execute("""SELECT p.id AS photo_id, t.tag AS animal
                FROM ai_tags t JOIN photos p
                  ON p.id=t.photo_id AND p.user_id=t.user_id
                WHERE t.user_id=%s AND p.deleted_at IS NULL
                  AND t.tag IN ('cat','dog','bird','horse','fish','wildlife')
                  AND NOT EXISTS (
                    SELECT 1 FROM ai_pet_labels l
                    WHERE l.user_id=t.user_id AND l.photo_id=t.photo_id)
                  AND t.score >= 0.27
                ORDER BY t.score DESC,p.id DESC LIMIT %s""", (user['id'],limit))
            return {'items':cur.fetchall()}

    return router
