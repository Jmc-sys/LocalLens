"""Private, per-photo tag corrections for LocalLens Smart Library.

Rejections suppress an incorrect automatic classification on this photo across
all future scans. Added tags survive future scans. This does NOT train CLIP or
change classifications for other photos.
"""
import re
from contextlib import contextmanager
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


class TagChange(BaseModel):
    tag: str = Field(min_length=1, max_length=80)
    action: Literal['add', 'reject']


def normalize_tag(value):
    """Stable form for concept labels and user-generated photo search tags."""
    tag = re.sub(r'\s+', '-', str(value).strip().lower())
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', tag):
        raise HTTPException(422, 'Use letters, numbers, spaces, hyphens or underscores (up to 80 characters)')
    return tag


@contextmanager
def database(get_connection):
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


def owned_photo(cur, user_id, photo_id, lock=False):
    cur.execute('''SELECT id FROM photos WHERE id=%s AND user_id=%s
                   AND deleted_at IS NULL''' + (' FOR UPDATE' if lock else ''),
                (photo_id, user_id))
    if not cur.fetchone():
        raise HTTPException(404, 'Photo not found')


def build_tag_feedback_router(get_connection, get_current_user):
    router = APIRouter(prefix='/api/ai', tags=['Smart Library photo tags'])

    @router.get('/photo/{photo_id}/tags')
    def photo_tags(photo_id: int, user=Depends(get_current_user)):
        uid = user['id']
        with database(get_connection) as (_, cur):
            owned_photo(cur, uid, photo_id)
            cur.execute('''SELECT t.tag, t.score,
                 CASE WHEN f.action='add' THEN 'manual' ELSE 'suggested' END AS source
                 FROM ai_tags t LEFT JOIN ai_tag_feedback f
                   ON f.user_id=t.user_id AND f.photo_id=t.photo_id AND f.tag=t.tag
                 WHERE t.user_id=%s AND t.photo_id=%s
                   AND (f.action IS NULL OR f.action <> 'reject')
                 ORDER BY CASE WHEN f.action='add' THEN 0 ELSE 1 END,
                          t.score DESC,t.tag''', (uid,photo_id))
            active = cur.fetchall()
            cur.execute('''SELECT tag FROM ai_tag_feedback
                 WHERE user_id=%s AND photo_id=%s AND action='reject'
                 ORDER BY tag''', (uid,photo_id))
            hidden = [r['tag'] for r in cur.fetchall()]
        return {'tags': active, 'hidden': hidden}

    @router.put('/photo/{photo_id}/tags')
    def correct_tag(photo_id: int, payload: TagChange, user=Depends(get_current_user)):
        tag = normalize_tag(payload.tag)
        uid = user['id']
        with database(get_connection) as (conn, cur):
            # Serialize photo tag writes with ai/scan.py; read after model inference.
            owned_photo(cur, uid, photo_id, lock=True)
            cur.execute('''INSERT INTO ai_tag_feedback(user_id,photo_id,tag,action)
                 VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE
                 action=VALUES(action),updated_at=NOW(6)''', (uid,photo_id,tag,payload.action))
            if payload.action == 'reject':
                cur.execute('DELETE FROM ai_tags WHERE photo_id=%s AND user_id=%s AND tag=%s',
                            (photo_id,uid,tag))
            else:
                cur.execute('''INSERT INTO ai_tags(photo_id,user_id,tag,score)
                     VALUES (%s,%s,%s,1.0)
                     ON DUPLICATE KEY UPDATE score=1.0''', (photo_id,uid,tag))
            conn.commit()
        return {'tag': tag, 'action': payload.action}

    @router.delete('/photo/{photo_id}/tags/{tag}')
    def undo_tag_change(photo_id: int, tag: str, user=Depends(get_current_user)):
        tag = normalize_tag(tag)
        uid = user['id']
        with database(get_connection) as (conn, cur):
            owned_photo(cur, uid, photo_id, lock=True)
            cur.execute('''SELECT action FROM ai_tag_feedback
                 WHERE photo_id=%s AND user_id=%s AND tag=%s FOR UPDATE''',
                        (photo_id,uid,tag))
            previous = cur.fetchone()
            if not previous:
                raise HTTPException(404, 'No manual correction for this tag')
            cur.execute('DELETE FROM ai_tag_feedback WHERE photo_id=%s AND user_id=%s AND tag=%s',
                        (photo_id,uid,tag))
            if previous['action'] == 'add':
                # Do not leave a formerly user-added tag as a high-confidence model prediction.
                cur.execute('DELETE FROM ai_tags WHERE photo_id=%s AND user_id=%s AND tag=%s',
                            (photo_id,uid,tag))
            # Recompute only this photo's suggestions to restore the model state.
            cur.execute('UPDATE ai_scans SET tags_done=0 WHERE photo_id=%s AND user_id=%s',
                        (photo_id,uid))
            conn.commit()
        return {'tag': tag, 'recheck_queued': True}

    return router
