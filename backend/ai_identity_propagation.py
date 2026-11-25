"""Re-match saved face embeddings after explicit face identification.

Uses CPU-only Python standard library; never reads/re-scans originals and never
learns from labels that were assigned automatically.
"""
from array import array
from math import sqrt


def vector(blob):
    try:
        v = array('f')
        v.frombytes(blob)
        if len(v) != 128 or not all(-100 < float(x) < 100 for x in v):
            return None
        mag = sqrt(sum(float(x) ** 2 for x in v))
        return tuple(float(x) / mag for x in v) if mag > 1e-8 else None
    except (TypeError, ValueError, OverflowError):
        return None


def propagate_confirmed_faces(cur, user_id):
    """Fill unknown faces from confirmed exemplars, or suggest when uncertain.

    Auto-apply a clear match to a confirmed identity; ambiguous faces remain suggestions.
    Existing person_id rows are NEVER changed. Work is scoped to one owner.
    """
    cur.execute('''SELECT f.id,f.photo_id,f.person_id,f.embedding FROM ai_faces f
        JOIN photos p ON p.id=f.photo_id AND p.user_id=f.user_id AND p.deleted_at IS NULL
        WHERE f.user_id=%s AND f.person_id IS NOT NULL AND f.assignment_source='confirmed'
        ORDER BY f.id DESC LIMIT 1600''', (user_id,))
    known = {}
    for row in cur.fetchall():
        v = vector(row['embedding'])
        if v is not None:
            known.setdefault(row['person_id'], []).append((v, row['photo_id']))
    if not known:
        return {'assigned': 0, 'suggested': 0}

    # Never reassign faces the owner explicitly marked unknown.
    # Never use deleted photos for automatic propagation.
    cur.execute('''SELECT f.id,f.embedding FROM ai_faces f
        JOIN photos p ON p.id=f.photo_id AND p.user_id=f.user_id AND p.deleted_at IS NULL
        LEFT JOIN ai_face_reviews r ON r.face_id=f.id AND r.user_id=f.user_id
        WHERE f.user_id=%s AND f.person_id IS NULL AND r.face_id IS NULL
        ORDER BY f.id LIMIT 5000''', (user_id,))
    pending = cur.fetchall()
    assigned = suggested = 0
    for row in pending:
        target = vector(row['embedding'])
        if target is None:
            continue
        scores = {}
        for person_id, samples in known.items():
            scores[person_id] = max(sum(a*b for a,b in zip(target, sample)) for sample,_ in samples)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        pid, score = ranked[0]
        gap = score - (ranked[1][1] if len(ranked) > 1 else -1.)
        sample_count = len({photo_id for _, photo_id in known[pid]})
        if score >= .50 and gap >= .08 and sample_count >= 1:
            cur.execute('''UPDATE ai_faces SET person_id=%s,suggested_person_id=NULL,
                similarity=%s,assignment_source='automatic'
                WHERE id=%s AND user_id=%s AND person_id IS NULL''',
                (pid,score,row['id'],user_id))
            assigned += cur.rowcount
        elif score >= .50 and gap >= .08:
            cur.execute('''UPDATE ai_faces SET suggested_person_id=%s,similarity=%s
                WHERE id=%s AND user_id=%s AND person_id IS NULL
                AND (suggested_person_id IS NULL OR similarity IS NULL OR similarity < %s)''',
                (pid,score,row['id'],user_id,score))
            suggested += cur.rowcount
    return {'assigned':assigned,'suggested':suggested}
