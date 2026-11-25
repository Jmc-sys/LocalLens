"""Promote genuinely strong existing face matches while the low-priority worker is idle.

Drop-in replacement for the v0.6.7 suggestion backfill. Review candidates include
both previously suggested and completely unnamed faces. No media files are read.
Only *manually confirmed* faces can serve as known references. A worker calls
promote_suggested_faces between photos, never from a foreground API request.
"""
import math
import os
import numpy as np


def _setting(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Scores are SFace cosine similarities, NOT calibrated probabilities. Thresholds
# are deliberately conservative; ambiguous faces remain in the owner review queue.
TWO_REFERENCE_SCORE = max(.60, min(.95, _setting('AI_FACE_AUTO_TWO_REFERENCES', .72)))
SINGLE_REFERENCE_SCORE = max(.70, min(.98, _setting('AI_FACE_AUTO_SINGLE_REFERENCE', .84)))
MIN_MARGIN = max(.08, min(.4, _setting('AI_FACE_AUTO_MIN_MARGIN', .12)))
SUGGEST_SCORE = .55


def vector(blob):
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        return None
    if len(blob) != 128 * 4:
        return None
    vec = np.frombuffer(blob, dtype='<f4')
    if vec.size != 128 or not np.all(np.isfinite(vec)):
        return None
    norm = float(np.linalg.norm(vec))
    return vec.astype(np.float32) / norm if math.isfinite(norm) and norm > 1e-8 else None


def choose_identity(vector_to_match, confirmed):
    """(person_id, score, safe_to_apply): references are user-confirmed only.

    confirmed = {person_id: [(normalized_vector, photo_id), ...]}.
    Auto-assigned faces must NEVER be fed back into this reference set.
    """
    if vector_to_match is None or not confirmed:
        return None, None, False
    scores = []
    for person_id, examples in confirmed.items():
        valid = [(v, pid) for v, pid in examples if v is not None]
        if not valid:
            continue
        top = max(float(np.dot(vector_to_match, v)) for v, _ in valid)
        photos = len({pid for _, pid in valid})
        scores.append((person_id, top, photos))
    if not scores:
        return None, None, False
    scores.sort(key=lambda s: s[1], reverse=True)
    person_id, best, photos = scores[0]
    runner = scores[1][1] if len(scores) > 1 else -1.0
    threshold = TWO_REFERENCE_SCORE if photos >= 2 else SINGLE_REFERENCE_SCORE
    safe = best >= threshold and best - runner >= MIN_MARGIN
    if best < SUGGEST_SCORE:
        return None, None, False
    return person_id, best, safe


def promote_suggested_faces(conn, user_id, after_id=0, limit=50):
    """Scan a bounded portion of ALL unknown faces and advance a resumable cursor.

    - Ignores deleted media and user-dismissed faces.
    - Never overwrites a confirmed or already named identity.
    - Uses one account's confirmed embeddings only.
    - Commits once per batch; the existing scheduler's upload/load gate applies.
    Returns (named_count, next_face_id). Cursor wraps to zero after a sweep.
    """
    limit = max(1, min(int(limit), 80))
    cur = conn.cursor(dictionary=True)
    assigned = 0
    try:
        cur.execute('SELECT enabled FROM ai_face_settings WHERE user_id=%s', (user_id,))
        if not bool((cur.fetchone() or {}).get('enabled')):
            return 0, after_id
        cur.execute('''SELECT f.embedding, f.person_id, f.photo_id
            FROM ai_faces f JOIN photos p ON p.id=f.photo_id AND p.user_id=f.user_id
                AND p.deleted_at IS NULL
            WHERE f.user_id=%s AND f.person_id IS NOT NULL
                AND f.assignment_source='confirmed'
            ORDER BY f.id DESC LIMIT 3000''', (user_id,))
        confirmed = {}
        for row in cur.fetchall():
            embedding = vector(row.get('embedding'))
            if embedding is not None:
                confirmed.setdefault(row['person_id'], []).append((embedding, row['photo_id']))
        if not confirmed:
            return 0, after_id
        query = '''SELECT f.id, f.embedding, f.suggested_person_id, f.similarity
            FROM ai_faces f
            JOIN photos p ON p.id=f.photo_id AND p.user_id=f.user_id
                AND p.deleted_at IS NULL
            LEFT JOIN ai_face_reviews review ON review.face_id=f.id
                AND review.user_id=f.user_id
            WHERE f.user_id=%s AND f.person_id IS NULL AND review.face_id IS NULL'''
        cur.execute(query+' AND f.id>%s ORDER BY f.id ASC LIMIT %s',
                    (user_id, after_id, limit))
        pending = cur.fetchall()
        # Reset rather than looping inside the same call, so periodic sweeps can
        # benefit from identities newly confirmed while browsing.
        if not pending:
            return 0, 0
        next_id = pending[-1]['id']
        for row in pending:
            pid, score, certain = choose_identity(vector(row.get('embedding')), confirmed)
            if pid is None:
                continue
            if certain:
                cur.execute('''UPDATE ai_faces f
                    LEFT JOIN ai_face_reviews r ON r.face_id=f.id AND r.user_id=f.user_id
                    SET f.person_id=%s, f.suggested_person_id=NULL,
                        f.similarity=%s, f.assignment_source='automatic'
                    WHERE f.id=%s AND f.user_id=%s AND f.person_id IS NULL AND r.face_id IS NULL''',
                    (pid, score, row['id'], user_id))
                assigned += cur.rowcount
            elif row.get('suggested_person_id') != pid or row.get('similarity') is None or float(row['similarity']) < score:
                # An uncertain suggestion appears preselected in Review Faces,
                # but is never considered a confirmed identity.
                cur.execute('''UPDATE ai_faces f
                    LEFT JOIN ai_face_reviews r ON r.face_id=f.id AND r.user_id=f.user_id
                    SET f.suggested_person_id=%s, f.similarity=%s
                    WHERE f.id=%s AND f.user_id=%s AND f.person_id IS NULL AND r.face_id IS NULL''',
                    (pid, score, row['id'], user_id))
        conn.commit()
        return assigned, next_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
