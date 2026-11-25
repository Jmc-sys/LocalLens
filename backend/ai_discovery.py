from ai_identity_propagation import propagate_confirmed_faces
"""Private AI smart search; face analysis opt-in per media owner.

AI indexing happens out-of-process in ai/scan.py. These routes only return
records belonging to the authenticated user, never to a shared-album viewer.
"""
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from PIL import Image, ImageOps
from photos import MEDIA_ROOT
from mysql.connector import Error as DatabaseError, IntegrityError

@contextmanager
def db(get_connection):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        yield conn, cur
    finally:
        cur.close()
        conn.close()

class FaceSetting(BaseModel):
    enabled: bool

class FaceName(BaseModel):
    name: str = Field(min_length=1, max_length=100)

def build_ai_router(get_connection, get_current_user):
    router = APIRouter(prefix='/api/ai', tags=['AI discovery'])

    @router.get('/tags')
    def tags(user=Depends(get_current_user)):
        with db(get_connection) as (_, cur):
            try:
                cur.execute('''SELECT t.tag, COUNT(*) AS count FROM ai_tags t
                  JOIN photos p ON p.id=t.photo_id AND p.user_id=t.user_id
                  WHERE t.user_id=%s AND p.deleted_at IS NULL
                  GROUP BY t.tag ORDER BY count DESC, t.tag''', (user['id'],))
                return cur.fetchall()
            except DatabaseError as exc:
                if getattr(exc, 'errno', None) in (1146, 1054):
                    raise HTTPException(503, 'AI database tables/columns are missing. Verify and apply ai_discovery.sql migration.') from exc
                raise

    @router.get('/search')
    def search(tag: Optional[str] = Query(None, min_length=1, max_length=80),
               person_id: Optional[int] = Query(None, ge=1),
               limit: int = Query(100, ge=1, le=100),
               offset: int = Query(0, ge=0), user=Depends(get_current_user)):
        if (tag is None) == (person_id is None):
            raise HTTPException(422, 'Choose a tag or a person')
        join = ('JOIN ai_tags a ON a.photo_id=p.id AND a.user_id=p.user_id AND a.tag=%s'
                if tag is not None else
                'JOIN ai_faces a ON a.photo_id=p.id AND a.user_id=p.user_id AND a.person_id=%s')
        value = tag if tag is not None else person_id
        with db(get_connection) as (_, cur):
            cur.execute(f'''SELECT DISTINCT p.id,p.original_filename,p.mime_type,p.media_type,
                 p.size_bytes,p.uploaded_at,EXISTS(SELECT 1 FROM photo_resources r
                 WHERE r.photo_id=p.id AND r.resource_type='live_video') AS is_live
                 FROM photos p {join} WHERE p.user_id=%s AND p.deleted_at IS NULL
                 ORDER BY p.uploaded_at DESC LIMIT %s OFFSET %s''',
                 (value,user['id'],limit,offset))
            return {'items':cur.fetchall(), 'limit':limit, 'offset':offset}

    @router.get('/status')
    def status(user=Depends(get_current_user)):
        with db(get_connection) as (_, cur):
            cur.execute('''SELECT COUNT(*) AS total FROM photos
                WHERE user_id=%s AND deleted_at IS NULL AND COALESCE(media_type,'photo')<>'video' ''',
                (user['id'],))
            total = cur.fetchone()['total']
            cur.execute('''SELECT COUNT(*) AS indexed FROM ai_scans s JOIN photos p ON p.id=s.photo_id
                WHERE s.user_id=%s AND s.tags_done=1 AND p.deleted_at IS NULL''', (user['id'],))
            indexed=cur.fetchone()['indexed']
            cur.execute('SELECT enabled FROM ai_face_settings WHERE user_id=%s', (user['id'],))
            enabled=bool((cur.fetchone() or {}).get('enabled'))
            scan = {'state': 'not_started', 'batch_total': 0,
                    'batch_processed': 0, 'batch_success': 0}
            try:
                # A global scan is visible to all accounts; a scoped scan only
                # appears to its owner. No other users' media details are returned.
                cur.execute("""SELECT id,state,batch_total,batch_processed,
                    batch_success,error_message,started_at,heartbeat_at,finished_at,
                    TIMESTAMPDIFF(SECOND,heartbeat_at,NOW()) AS age_seconds
                    FROM ai_scan_jobs
                    WHERE scope_user_id IS NULL OR scope_user_id=%s
                    ORDER BY id DESC LIMIT 1""", (user['id'],))
                latest = cur.fetchone()
                if latest:
                    scan = dict(latest)
                    age = max(0, int(scan.get('age_seconds') or 0))
                    scan['age_seconds'] = age
                    if scan['state'] in ('starting','running') and age > 90:
                        scan['state'] = 'interrupted'
            except DatabaseError as exc:
                if getattr(exc,'errno',None) == 1146:
                    scan['state'] = 'setup_required'
                else:
                    raise
            return {'total_photos':total,'tagged_photos':indexed,
                    'faces_enabled':enabled,'scan':scan}

    @router.put('/face-settings')
    def face_settings(setting: FaceSetting, user=Depends(get_current_user)):
        uid = user['id']
        with db(get_connection) as (conn,cur):
            cur.execute('''INSERT INTO ai_face_settings(user_id,enabled) VALUES (%s,%s)
                 ON DUPLICATE KEY UPDATE enabled=VALUES(enabled)''', (uid,setting.enabled))
            if setting.enabled:
                # Re-index this user's faces when switching opt-in back on.
                cur.execute('UPDATE ai_scans SET faces_done=0 WHERE user_id=%s', (uid,))
            else:
                # Withdrawal removes biometric vectors and names, not original photos.
                cur.execute('DELETE FROM ai_face_reviews WHERE user_id=%s',(uid,))
                cur.execute('DELETE FROM ai_faces WHERE user_id=%s',(uid,))
                cur.execute('DELETE FROM ai_people WHERE user_id=%s',(uid,))
                cur.execute('UPDATE ai_scans SET faces_done=0 WHERE user_id=%s',(uid,))
            conn.commit()
        return {'faces_enabled':setting.enabled}

    @router.get('/faces')
    def faces(limit: int=Query(100, ge=1, le=200), offset: int=Query(0, ge=0),
              review: Optional[str]=Query(None), user=Depends(get_current_user)):
        if review not in (None, 'pending', 'unknown', 'named'):
            raise HTTPException(422, 'review must be pending, unknown or named')
        where = {
            None: '',
            'pending': ' AND f.person_id IS NULL AND r.face_id IS NULL',
            'unknown': " AND f.person_id IS NULL AND r.decision='unknown'",
            'named': ' AND f.person_id IS NOT NULL',
        }[review]
        with db(get_connection) as (_,cur):
            cur.execute(f'''SELECT f.id,f.photo_id,f.person_id,p.display_name,
                       f.suggested_person_id,s.display_name AS suggested_name,
                       f.similarity,r.decision AS review_decision FROM ai_faces f
                JOIN photos ph ON ph.id=f.photo_id AND ph.user_id=f.user_id AND ph.deleted_at IS NULL
                LEFT JOIN ai_people p ON p.id=f.person_id AND p.user_id=f.user_id
                LEFT JOIN ai_people s ON s.id=f.suggested_person_id AND s.user_id=f.user_id
                LEFT JOIN ai_face_reviews r ON r.face_id=f.id AND r.user_id=f.user_id
                WHERE f.user_id=%s {where} ORDER BY f.id DESC LIMIT %s OFFSET %s''',
                (user['id'],limit,offset))
            return cur.fetchall()

    @router.post('/faces/{face_id}/name')
    def name_face(face_id:int, payload:FaceName, user=Depends(get_current_user)):
        name=payload.name.strip()
        if not name: raise HTTPException(422,'Name cannot be blank')
        with db(get_connection) as (conn,cur):
            cur.execute('SELECT id FROM ai_faces WHERE id=%s AND user_id=%s',(face_id,user['id']))
            if not cur.fetchone(): raise HTTPException(404,'Face not found')
            cur.execute('''INSERT INTO ai_people(user_id,display_name) VALUES (%s,%s)
                ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)''',(user['id'],name))
            person_id=cur.lastrowid
            cur.execute('''UPDATE ai_faces SET person_id=%s,suggested_person_id=NULL,similarity=NULL,assignment_source='confirmed'
                 WHERE id=%s AND user_id=%s''',(person_id,face_id,user['id']))
            cur.execute('DELETE FROM ai_face_reviews WHERE face_id=%s AND user_id=%s', (face_id,user['id']))
            propagate_confirmed_faces(cur, user['id'])
            conn.commit()
        return {'id':face_id,'person_id':person_id,'name':name}

    @router.post('/faces/{face_id}/confirm')
    def confirm_face(face_id:int, user=Depends(get_current_user)):
        with db(get_connection) as (conn,cur):
            cur.execute('''UPDATE ai_faces SET person_id=suggested_person_id,
                suggested_person_id=NULL,similarity=NULL,assignment_source='confirmed' WHERE id=%s AND user_id=%s
                AND suggested_person_id IS NOT NULL''',(face_id,user['id']))
            if cur.rowcount != 1: raise HTTPException(404,'No suggestion to confirm')
            cur.execute('DELETE FROM ai_face_reviews WHERE face_id=%s AND user_id=%s', (face_id,user['id']))
            propagate_confirmed_faces(cur, user['id'])
            conn.commit()
        return {'confirmed':True}

    @router.get('/faces/{face_id}/crop')
    def face_crop(face_id:int, user=Depends(get_current_user)):
        with db(get_connection) as (_,cur):
            cur.execute('''SELECT f.x,f.y,f.w,f.h,p.storage_path FROM ai_faces f
                JOIN photos p ON p.id=f.photo_id AND p.user_id=f.user_id AND p.deleted_at IS NULL
                WHERE f.id=%s AND f.user_id=%s''',(face_id,user['id']))
            face=cur.fetchone()
        if not face: raise HTTPException(404,'Face unavailable')
        root=(MEDIA_ROOT/'users'/str(user['id'])/'originals').resolve()
        path=Path(face['storage_path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404,'Original missing')
        try:
            with Image.open(path) as raw:
                img=ImageOps.exif_transpose(raw).convert('RGB')
                w,h=img.size
                x,y,fw,fh=(float(face[k]) for k in ('x','y','w','h'))
                box=(max(0,int((x-.12*fw)*w)),max(0,int((y-.12*fh)*h)),
                     min(w,int((x+1.12*fw)*w)),min(h,int((y+1.12*fh)*h)))
                img=img.crop(box); img.thumbnail((240,240))
                output=BytesIO(); img.save(output,format='JPEG',quality=80)
            return Response(output.getvalue(),media_type='image/jpeg',
                            headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
        except (OSError, ValueError):
            raise HTTPException(404,'Face crop unavailable')

    @router.get('/people')
    def people(user=Depends(get_current_user)):
        with db(get_connection) as (_,cur):
            cur.execute("""SELECT p.id,p.display_name,COUNT(f.id) AS photo_count
                FROM ai_people p LEFT JOIN ai_faces f
                  ON f.person_id=p.id AND f.user_id=p.user_id
                WHERE p.user_id=%s GROUP BY p.id,p.display_name
                ORDER BY p.display_name LIMIT 500""",(user['id'],))
            return cur.fetchall()

    @router.patch('/people/{person_id}')
    def rename_person(person_id: int, payload: FaceName, user=Depends(get_current_user)):
        name=payload.name.strip()
        if not name: raise HTTPException(422,'Name cannot be blank')
        with db(get_connection) as (conn,cur):
            try:
                cur.execute("UPDATE ai_people SET display_name=%s WHERE id=%s AND user_id=%s",
                            (name,person_id,user['id']))
            except IntegrityError as exc:
                conn.rollback()
                raise HTTPException(409,'A person with this name already exists') from exc
            if cur.rowcount != 1: raise HTTPException(404,'Person not found or name unchanged')
            conn.commit()
        return {'id':person_id,'name':name}

    @router.post('/faces/{face_id}/unknown')
    def mark_unknown(face_id: int, user=Depends(get_current_user)):
        with db(get_connection) as (conn,cur):
            cur.execute('SELECT id FROM ai_faces WHERE id=%s AND user_id=%s AND person_id IS NULL',
                        (face_id,user['id']))
            if not cur.fetchone(): raise HTTPException(404,'Unidentified face not found')
            cur.execute("""INSERT INTO ai_face_reviews(face_id,user_id,decision)
              VALUES (%s,%s,'unknown') ON DUPLICATE KEY UPDATE
              decision='unknown',reviewed_at=NOW()""",(face_id,user['id']))
            conn.commit()
        return {'id':face_id,'review':'unknown'}

    @router.post('/faces/{face_id}/reopen')
    def reopen_face(face_id: int, user=Depends(get_current_user)):
        with db(get_connection) as (conn,cur):
            cur.execute('DELETE FROM ai_face_reviews WHERE face_id=%s AND user_id=%s',
                        (face_id,user['id']))
            if cur.rowcount != 1: raise HTTPException(404,'Reviewed face not found')
            conn.commit()
        return {'id':face_id,'review':'pending'}

    return router
