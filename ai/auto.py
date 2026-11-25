"""Low-priority, resumable LocalLens auto indexer.

Runs as a standalone Compose service. It waits for all accounts to finish uploads
and browsing; only user accounts with auto_enabled=1 are indexed. Jobs record
progress per image. A clean pause always occurs between images.
"""
import logging
import os
import time

import numpy as np

import scan
from review_auto_resolve import promote_suggested_faces

LOG = logging.getLogger('locallens-ai-auto')
PRESSURE_IDLE = max(5, int(os.getenv('AI_PRESSURE_COOLDOWN_SECONDS', '12')))
UPLOAD_IDLE = max(5, int(os.getenv('AI_UPLOAD_IDLE_SECONDS', '12')))
BATCH = max(1, min(100, int(os.getenv('AI_BATCH_LIMIT', '20'))))
PAUSE = max(0.5, float(os.getenv('AI_SCAN_PAUSE_SECONDS', '1.5')))


def idle_reason(conn):
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('''SELECT TIMESTAMPDIFF(SECOND,last_browse_at,NOW()) AS browse_age,
                       TIMESTAMPDIFF(SECOND,last_upload_at,NOW()) AS upload_age
                       FROM ai_index_activity WHERE id=1''')
        data = cur.fetchone() or {}
        if data.get('upload_age') is not None and data['upload_age'] < UPLOAD_IDLE:
            return 'recent_upload'
        if data.get('browse_age') is not None and data['browse_age'] < PRESSURE_IDLE:
            return 'high_demand'
        cur.execute('''SELECT COUNT(*) AS n FROM ai_upload_leases
                       WHERE heartbeat_at > DATE_SUB(NOW(6), INTERVAL 45 SECOND)''')
        if cur.fetchone()['n']:
            return 'uploading'
        return None
    finally:
        cur.close()


def enabled_users(conn):
    cur = conn.cursor()
    try:
        cur.execute('SELECT user_id FROM ai_index_control WHERE auto_enabled=1 ORDER BY updated_at')
        return [row[0] for row in cur.fetchall()]
    finally:
        cur.close()


def still_enabled(conn, user_id):
    cur = conn.cursor()
    try:
        cur.execute('SELECT auto_enabled FROM ai_index_control WHERE user_id=%s', (user_id,))
        row = cur.fetchone()
        return bool(row and row[0])
    finally:
        cur.close()


def face_health(conn, state, detail=None):
    cur = conn.cursor()
    try:
        cur.execute('''UPDATE ai_face_model_health
                       SET state=%s,detail=%s,updated_at=NOW(6) WHERE id=1''',
                    (state, (detail or '')[:300] or None))
        conn.commit()
    finally:
        cur.close()


def auto_name_existing_faces(conn, user_id, after_id=0, max_faces=120):
    """Auto-name unreviewed faces using existing confirmed identity examples."""
    cur=conn.cursor(dictionary=True)
    renamed=0
    try:
        cur.execute('''SELECT COUNT(DISTINCT photo_id) AS n FROM ai_faces
                       WHERE user_id=%s AND person_id IS NOT NULL
                         AND assignment_source='confirmed' ''', (user_id,))
        if cur.fetchone()['n'] < 1:
            return 0, after_id
        query = '''SELECT f.id, f.embedding FROM ai_faces f
                   LEFT JOIN ai_face_reviews r ON r.face_id=f.id AND r.user_id=f.user_id
                   WHERE f.user_id=%s AND f.person_id IS NULL AND r.face_id IS NULL'''
        cur.execute(query + ' AND f.id>%s ORDER BY f.id ASC LIMIT %s',
                    (user_id, after_id, max_faces))
        unknown=cur.fetchall()
        if not unknown:
            cur.execute(query + ' ORDER BY f.id ASC LIMIT %s', (user_id, max_faces))
            unknown=cur.fetchall()
        next_id=unknown[-1]['id'] if unknown else 0
        for face in unknown:
            if idle_reason(conn) or not still_enabled(conn,user_id):
                break
            vector=np.frombuffer(face['embedding'], dtype=np.float32)
            if not vector.size:
                continue
            person, score, certain=scan.face_match(cur,user_id,vector)
            if certain:
                cur.execute('''UPDATE ai_faces SET person_id=%s,
                               suggested_person_id=NULL,similarity=%s,
                               assignment_source='automatic'
                               WHERE id=%s AND user_id=%s AND person_id IS NULL''',
                            (person,score,face['id'],user_id))
                renamed+=cur.rowcount
        conn.commit()
        if renamed:
            LOG.info('Auto-matched %s previously unreviewed face(s) for one account',renamed)
        return renamed, next_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def run():
    LOG.info('Smart Library ready: %ss foreground pressure cooldown, %ss upload cooldown; one CPU core',
             PRESSURE_IDLE, UPLOAD_IDLE)
    model = None
    faces = None
    conn = None
    last_reconcile = {}
    last_reconcile_cursor = {}
    last_suggestion_check = {}
    last_suggestion_cursor = {}
    while True:
        try:
            if conn is None or not conn.is_connected():
                conn = scan.get_db()
            beat=conn.cursor()
            beat.execute('UPDATE ai_scheduler_heartbeat SET last_seen_at=NOW(6) WHERE id=1')
            conn.commit()
            beat.close()
            reason = idle_reason(conn)
            if reason:
                time.sleep(5)
                continue
            users = enabled_users(conn)
            if not users:
                time.sleep(10)
                continue
            # One named advisory lock is shared with the manual CLI scanner.
            lock_cur = conn.cursor()
            lock_cur.execute("SELECT GET_LOCK('locallens_ai_indexing',0)")
            locked = lock_cur.fetchone()[0] == 1
            lock_cur.close()
            if not locked:
                time.sleep(8)
                continue
            try:
                worked = False
                for uid in users:
                    if idle_reason(conn) or not still_enabled(conn, uid):
                        break
                    # Revisit previously suggested names without rereading photos.
                    # Respect the same foreground/upload pause as image scanning.
                    if time.monotonic() - last_suggestion_check.get(uid, 0) > 30:
                        last_suggestion_check[uid] = time.monotonic()
                        changed, last_suggestion_cursor[uid] = promote_suggested_faces(
                            conn, uid, after_id=last_suggestion_cursor.get(uid, 0), limit=40)
                        if changed:
                            LOG.info('Assigned %d high-confidence suggested face(s)', changed)
                    rows = scan.candidates(conn, uid, BATCH)
                    if time.monotonic() - last_reconcile.get(uid, 0) > 30:
                        last_reconcile[uid] = time.monotonic()
                        _, last_reconcile_cursor[uid] = auto_name_existing_faces(
                            conn, uid, after_id=last_reconcile_cursor.get(uid, 0))
                    if not rows:
                        continue
                    worked = True
                    job = scan.ScanJob(conn, uid, len(rows))
                    done = successes = 0
                    try:
                        if model is None:
                            model = scan.create_clip()
                        if faces is None and any(r['faces_enabled'] and not r['faces_done'] for r in rows):
                            try:
                                faces = scan.load_face_models()
                                face_health(conn, 'ready')
                            except Exception as exc:
                                face_health(conn, 'failed', type(exc).__name__ + ': ' + str(exc)[:220])
                                raise
                        job.progress(0, 0)
                        for row in rows:
                            if idle_reason(conn) or not still_enabled(conn, uid):
                                break
                            successes += bool(scan.scan_one(conn, row, *model, faces))
                            done += 1
                            job.progress(done, successes)
                            if done < len(rows):
                                time.sleep(PAUSE)
                        job.finish('completed' if done == len(rows) else 'paused')
                        if done != len(rows):
                            LOG.info('Batch paused after %d/%d photos due to foreground activity', done, len(rows))
                            break
                    except Exception as exc:
                        job.finish('failed', type(exc).__name__ + ': ' + str(exc)[:220])
                        LOG.exception('AI batch failed; will retry after cooldown')
                        time.sleep(60)
                    finally:
                        job.stop_event.set()
            finally:
                release_cur = conn.cursor()
                try:
                    release_cur.execute("SELECT RELEASE_LOCK('locallens_ai_indexing')")
                    release_cur.fetchone()
                finally:
                    release_cur.close()
            time.sleep(8 if worked else 15)
        except Exception:
            LOG.exception('Scheduler database loop error; retrying without affecting user traffic')
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            conn = None
            time.sleep(30)


if __name__ == '__main__':
    try:
        os.nice(12)  # lower CPU scheduling priority on Linux
    except (AttributeError, OSError):
        pass
    run()
