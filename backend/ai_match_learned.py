"""Owner-scoped, bounded matching of stored faces against *confirmed* identities.

This endpoint operates on existing ai_faces.embeddings only. It does not rescan
photos, need OpenCV/NumPy, or depend on the ai-indexer scheduler being online.
Each request processes at most 40 pending faces; the browser advances the cursor
between requests, leaving the backend responsive. No schema migration required.
"""
from __future__ import annotations

import math
import struct
from collections import defaultdict
from contextlib import contextmanager
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

VECTOR_SIZE = 128
REFERENCE_LIMIT = 2000
MAX_PER_IDENTITY = 12
SINGLE_EXAMPLE_THRESHOLD = 0.82
MULTIPLE_EXAMPLE_THRESHOLD = 0.68
MIN_WINNER_MARGIN = 0.10


class MatchBatch(BaseModel):
    after_id: int = Field(default=0, ge=0)
    limit: int = Field(default=30, ge=1, le=40)


@contextmanager
def database(get_connection):
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        yield connection, cursor
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def as_unit_vector(blob):
    """SFace embeddings are stored as 128 float32 values (little endian)."""
    if not isinstance(blob, (bytes, bytearray, memoryview)) or len(blob) != VECTOR_SIZE * 4:
        return None
    values = struct.unpack('<128f', bytes(blob))
    if not all(math.isfinite(v) for v in values):
        return None
    length = math.sqrt(sum(v*v for v in values))
    if length < 1e-8 or not math.isfinite(length):
        return None
    return tuple(v / length for v in values)


def best_confirmed_match(candidate, references):
    """Return (person_id, similarity) only for strong, unambiguous evidence.

    Automatic assignments and tentative guesses NEVER become reference faces.
    Require one genuine confirmed example; two different photos reduce the
    threshold. An identity must beat its nearest rival by MIN_WINNER_MARGIN.
    """
    if candidate is None:
        return None
    ranked = []
    for person_id, examples in references.items():
        if not examples:
            continue
        best = max(sum(x*y for x, y in zip(candidate, known)) for known, _ in examples)
        distinct_photos = len({photo_id for _, photo_id in examples})
        ranked.append((best, person_id, distinct_photos))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    score, person_id, examples = ranked[0]
    competitor_score = ranked[1][0] if len(ranked) > 1 else -1.0
    minimum = MULTIPLE_EXAMPLE_THRESHOLD if examples >= 2 else SINGLE_EXAMPLE_THRESHOLD
    if score < minimum or score - competitor_score < MIN_WINNER_MARGIN:
        return None
    return person_id, score


def load_confirmed(cursor, user_id):
    cursor.execute('''SELECT f.person_id, f.photo_id, f.embedding FROM ai_faces f
        JOIN photos p ON p.id=f.photo_id AND p.user_id=f.user_id
        WHERE f.user_id=%s AND f.person_id IS NOT NULL
          AND f.assignment_source='confirmed' AND p.deleted_at IS NULL
        ORDER BY f.id DESC LIMIT %s''', (user_id, REFERENCE_LIMIT))
    references = defaultdict(list)
    photos = defaultdict(set)
    for item in cursor.fetchall():
        pid = item['person_id']
        if len(references[pid]) >= MAX_PER_IDENTITY or item['photo_id'] in photos[pid]:
            continue
        face = as_unit_vector(item['embedding'])
        if face is not None:
            references[pid].append((face, item['photo_id']))
            photos[pid].add(item['photo_id'])
    return references


def match_batch(get_connection, user_id, after_id, limit):
    with database(get_connection) as (conn, cur):
        # This route is separate from the AI scheduler and works while offline.
        # Lock prevents two simultaneous runs for the same account.
        lock_name = 'locallens_match_faces_' + str(user_id)
        cur.execute('SELECT GET_LOCK(%s, 0) AS acquired', (lock_name,))
        if not (cur.fetchone() or {}).get('acquired'):
            raise HTTPException(409, 'Face matching already running for this account')
        try:
            cur.execute('SELECT enabled FROM ai_face_settings WHERE user_id=%s', (user_id,))
            if not (cur.fetchone() or {}).get('enabled'):
                raise HTTPException(409, 'Face recognition is disabled for this account')
            # Do not compete with real-time uploads; wait until they complete.
            cur.execute('''SELECT COUNT(*) AS active FROM ai_upload_leases
                WHERE heartbeat_at > DATE_SUB(NOW(6), INTERVAL 45 SECOND)''')
            if (cur.fetchone() or {}).get('active'):
                return {'matched': 0, 'checked': 0, 'next_after': after_id,
                        'has_more': False, 'paused_for_upload': True}

            references = load_confirmed(cur, user_id)
            if not references:
                return {'matched': 0, 'checked': 0, 'next_after': after_id,
                        'has_more': False, 'needs_examples': True}
            # Exclude previously dismissed/Unknown/Not-a-face detections and
            # media in Trash; verify user ownership in every query.
            cur.execute('''SELECT f.id, f.embedding FROM ai_faces f
                JOIN photos p ON p.id=f.photo_id AND p.user_id=f.user_id
                LEFT JOIN ai_face_reviews review
                  ON review.face_id=f.id AND review.user_id=f.user_id
                WHERE f.user_id=%s AND f.person_id IS NULL AND review.face_id IS NULL
                  AND p.deleted_at IS NULL AND f.id>%s
                ORDER BY f.id ASC LIMIT %s''', (user_id, after_id, limit))
            candidates = cur.fetchall()
            matched = 0
            for face in candidates:
                match = best_confirmed_match(as_unit_vector(face.get('embedding')), references)
                if match is None:
                    continue
                pid, score = match
                cur.execute('''UPDATE ai_faces f
                    JOIN photos p ON p.id=f.photo_id AND p.user_id=f.user_id
                    LEFT JOIN ai_face_reviews review ON review.face_id=f.id
                        AND review.user_id=f.user_id
                    SET f.person_id=%s, f.suggested_person_id=NULL,
                        f.similarity=%s, f.assignment_source='automatic'
                    WHERE f.user_id=%s AND f.id=%s AND f.person_id IS NULL
                      AND review.face_id IS NULL AND p.deleted_at IS NULL''',
                    (pid, score, user_id, face['id']))
                matched += cur.rowcount
            conn.commit()
            return {'matched': matched, 'checked': len(candidates),
                    'next_after': candidates[-1]['id'] if candidates else after_id,
                    'has_more': len(candidates) == limit,
                    'paused_for_upload': False}
        finally:
            # Named lock is connection-scoped; release even if matching fails.
            cur.execute('SELECT RELEASE_LOCK(%s) AS released', (lock_name,))
            cur.fetchone()


def build_match_learned_router(get_connection, get_current_user):
    router = APIRouter(prefix='/api/ai', tags=['AI automation'])

    @router.post('/automation/match-learned')
    def match_learned(payload: MatchBatch, user=Depends(get_current_user)):
        return match_batch(get_connection, user['id'], payload.after_id, payload.limit)

    return router
