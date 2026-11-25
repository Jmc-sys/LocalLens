"""Read-only user-scoped manual identity counters for Smart Library."""
from fastapi import APIRouter, Depends


def build_manual_identity_stats_router(get_connection, get_current_user):
    router = APIRouter(prefix='/api/ai', tags=['Smart Library metrics'])

    @router.get('/identity/manual-stats')
    def manual_stats(user=Depends(get_current_user)):
        uid = user['id']
        conn = get_connection()
        cur = None
        try:
            cur = conn.cursor(dictionary=True)
            # The 'confirmed' marker denotes a user-confirmed assignment, not
            # other embeddings the AI assigned from that example.
            cur.execute('''SELECT COUNT(*) AS n FROM ai_faces f
              JOIN photos p ON p.id=f.photo_id AND p.user_id=f.user_id
              WHERE f.user_id=%s AND p.deleted_at IS NULL
                AND f.person_id IS NOT NULL AND f.assignment_source='confirmed' ''', (uid,))
            faces = int((cur.fetchone() or {}).get('n') or 0)
            return {'faces_named_by_you': faces}
        finally:
            if cur is not None:
                cur.close()
            conn.close()
    return router
