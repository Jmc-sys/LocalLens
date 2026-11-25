"""Group unfamiliar faces, so an owner identifies identities instead of photos.

Pure Python vector matching and bounded review queries; no image reads in the
request path. Account-scoped and opt-in. Clusters are review suggestions, not
proof of identity. Verified identities never get overwritten.
"""
from array import array
from contextlib import contextmanager
from math import sqrt
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

# Selected feature coordinates for approximate shortlist, no persistent index.
BANDS = ((2,7,12,19,31,43),(1,9,22,34,47,59),
         (4,13,27,51,72,96),(5,18,39,63,88,113))
MAX_GROUP_SCAN = 2500
GROUP_THRESHOLD = .75
CONFIDENT_GROUP = .82

@contextmanager
def db(get_connection):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        yield conn,cur
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def normalize(blob):
    try:
        a=array('f'); a.frombytes(blob)
        if len(a)!=128 or not all(-100 < float(x) < 100 for x in a):
            return None
        norm=sqrt(sum(float(x)*x for x in a))
        return tuple(float(x)/norm for x in a) if norm > 1e-8 else None
    except (TypeError,ValueError,OverflowError):
        return None


def cosine(a,b):
    return sum(x*y for x,y in zip(a,b))


def signatures(v):
    return [(i,sum(1 << bit for bit,idx in enumerate(band) if v[idx]>=0))
            for i,band in enumerate(BANDS)]


def group_faces(rows):
    """Approximate bounded clustering; grouping never makes identity decisions.

    For efficiency only compare vector signatures plus the last few groups.
    This can split a single person into separate groups; it cannot assign names.
    """
    groups=[]; buckets={}
    for row in rows:
        v=normalize(row.get('embedding'))
        if v is None:continue
        keys=signatures(v)
        indices=set(range(max(0,len(groups)-10),len(groups)))
        for key in keys: indices.update(buckets.get(key, ()))
        # Account for already suggested identity, without assuming correct.
        suggested=row.get('suggested_person_id')
        if suggested is not None:
            indices.update(i for i,g in enumerate(groups) if g['suggested_person_id']==suggested)
        best_idx=None; best_score=GROUP_THRESHOLD
        for index in indices:
            group=groups[index]
            score=cosine(group['_vector'],v)
            if score > best_score:
                best_score=score; best_idx=index
        if best_idx is None:
            best_idx=len(groups)
            groups.append({'id':row['id'],'photo_id':row['photo_id'],'count':0,
                           'suggested_name':row.get('suggested_name'),
                           'suggested_person_id':suggested,
                           '_vector':v})
            for key in keys:buckets.setdefault(key,set()).add(best_idx)
        groups[best_idx]['count']+=1
        if suggested is not None and row.get('suggested_name'):
            votes = groups[best_idx].setdefault('_suggestion_votes', {})
            item = votes.setdefault(suggested, [0, row['suggested_name']])
            item[0] += 1
    for group in groups:
        group.pop('_vector')
        votes = group.pop('_suggestion_votes', {})
        if votes:
            ranked = sorted(votes.items(), key=lambda item: item[1][0], reverse=True)
            if len(ranked) == 1 or ranked[0][1][0] > ranked[1][1][0]:
                group['suggested_person_id'] = ranked[0][0]
                group['suggested_name'] = ranked[0][1][1]
            else:
                group['suggested_person_id'] = None
                group['suggested_name'] = None
    return groups


def scan_pending(cur,user_id,limit=MAX_GROUP_SCAN):
    cur.execute('''SELECT f.id,f.photo_id,f.embedding,f.suggested_person_id,
                         person.display_name AS suggested_name
        FROM ai_faces f
        JOIN photos p ON p.id=f.photo_id AND p.user_id=f.user_id
                 AND p.deleted_at IS NULL
        LEFT JOIN ai_face_reviews r ON r.face_id=f.id AND r.user_id=f.user_id
        LEFT JOIN ai_people person ON person.id=f.suggested_person_id
                                 AND person.user_id=f.user_id
        WHERE f.user_id=%s AND f.person_id IS NULL AND r.face_id IS NULL
        ORDER BY f.id DESC LIMIT %s''',(user_id,limit))
    return cur.fetchall()


def require_enabled(cur,uid):
    cur.execute('SELECT enabled FROM ai_face_settings WHERE user_id=%s',(uid,))
    if not bool((cur.fetchone() or {}).get('enabled')):
        raise HTTPException(409,'Face recognition is disabled for this account')


def selected_group(cur,uid,face_id):
    # Recalculate membership against current pending records instead of trusting
    # browser-supplied lists of face IDs. Conservative threshold for bulk labels.
    rows=scan_pending(cur,uid)
    rep=next((r for r in rows if r['id']==face_id),None)
    if rep is None:raise HTTPException(404,'Face already identified or no longer pending')
    vector=normalize(rep['embedding'])
    if vector is None:raise HTTPException(409,'Face embedding unavailable')
    members=[r['id'] for r in rows if (v:=normalize(r['embedding'])) is not None
             and cosine(vector,v)>=CONFIDENT_GROUP]
    return members or [face_id]

class NameFaceGroup(BaseModel):
    name: str=Field(min_length=1,max_length=100)


def build_face_group_router(get_connection,get_current_user):
    router=APIRouter(prefix='/api/ai',tags=['Smart Library face review'])

    @router.get('/faces/known-gallery')
    def known_gallery(user=Depends(get_current_user)):
        """One face from the newest eligible photo for each already named person.

        No embeddings or original media paths are returned. Face crops are served
        through the existing owner-authenticated `/api/ai/faces/{id}/crop` route.
        """
        uid = user['id']
        with db(get_connection) as (_, cur):
            require_enabled(cur, uid)
            cur.execute('''
                WITH ranked AS (
                    SELECT f.person_id, f.id AS face_id,
                           COUNT(*) OVER(PARTITION BY f.person_id) AS face_count,
                           ROW_NUMBER() OVER(
                               PARTITION BY f.person_id
                               ORDER BY (p.captured_at IS NULL) ASC,
                                        p.captured_at DESC,
                                        p.uploaded_at DESC,
                                        p.id DESC, f.id DESC
                           ) AS recent_rank
                    FROM ai_faces f
                    JOIN photos p ON p.id=f.photo_id AND p.user_id=f.user_id
                    WHERE f.user_id=%s AND f.person_id IS NOT NULL
                      AND p.deleted_at IS NULL
                )
                SELECT person.id, person.display_name, ranked.face_id,
                       ranked.face_count
                FROM ranked JOIN ai_people person
                  ON person.id=ranked.person_id AND person.user_id=%s
                WHERE ranked.recent_rank=1
                ORDER BY person.display_name ASC LIMIT 250
            ''', (uid, uid))
            return {'items': cur.fetchall()}

    @router.get('/faces/review-groups')
    def review_groups(page:int=Query(0,ge=0,le=1000),limit:int=Query(24,ge=1,le=40),
                      user=Depends(get_current_user)):
        uid=user['id']
        with db(get_connection) as (_,cur):
            require_enabled(cur,uid)
            rows=scan_pending(cur,uid)
            groups=group_faces(rows)
            # One count query ensures the displayed total isn't confused with group count.
            cur.execute('''SELECT COUNT(*) AS total FROM ai_faces f
                JOIN photos p ON p.id=f.photo_id AND p.user_id=f.user_id
                    AND p.deleted_at IS NULL
                LEFT JOIN ai_face_reviews r ON r.face_id=f.id AND r.user_id=f.user_id
                WHERE f.user_id=%s AND f.person_id IS NULL AND r.face_id IS NULL''',(uid,))
            total=cur.fetchone()['total']
        start=page*limit
        return {'items':groups[start:start+limit],
                'people_to_review':len(groups),'unidentified_detections':total,
                'has_more':start+limit<len(groups),
                'truncated':total>MAX_GROUP_SCAN,'page':page}

    @router.post('/faces/review-groups/{face_id}/name')
    def name_group(face_id:int,payload:NameFaceGroup,user=Depends(get_current_user)):
        uid=user['id']; name=payload.name.strip()
        if not name:raise HTTPException(422,'Name required')
        with db(get_connection) as (conn,cur):
            require_enabled(cur,uid)
            members=selected_group(cur,uid,face_id)
            cur.execute('''INSERT INTO ai_people(user_id,display_name) VALUES(%s,%s)
              ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)''',(uid,name))
            pid=cur.lastrowid
            # Explicit owner naming is a *single* confirmed identity example.
            cur.execute('''UPDATE ai_faces SET person_id=%s,suggested_person_id=NULL,
                similarity=NULL,assignment_source='confirmed'
                WHERE id=%s AND user_id=%s AND person_id IS NULL''',(pid,face_id,uid))
            if cur.rowcount!=1:raise HTTPException(409,'Face changed; refresh review')
            auto=0
            for member in members:
                if member==face_id:continue
                cur.execute('''UPDATE ai_faces SET person_id=%s,suggested_person_id=NULL,
                    similarity=NULL,assignment_source='automatic'
                    WHERE id=%s AND user_id=%s AND person_id IS NULL''',(pid,member,uid))
                auto+=cur.rowcount
            from ai_identity_propagation import propagate_confirmed_faces
            extra=propagate_confirmed_faces(cur,uid)
            conn.commit()
        return {'name':name,'confirmed':1,'auto_named':auto+extra['assigned']}

    @router.post('/faces/review-groups/{face_id}/unknown')
    def mark_group_unknown(face_id:int,user=Depends(get_current_user)):
        uid=user['id']
        with db(get_connection) as (conn,cur):
            require_enabled(cur,uid)
            members=selected_group(cur,uid,face_id)
            cur.executemany('''INSERT INTO ai_face_reviews(face_id,user_id,decision)
                VALUES(%s,%s,'unknown') ON DUPLICATE KEY UPDATE decision='unknown',
                reviewed_at=NOW()''',[(face_id,uid) for face_id in members])
            conn.commit()
        return {'dismissed':len(members)}
    return router
