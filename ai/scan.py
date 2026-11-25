#!/usr/bin/env python3
"""Low-priority local image indexing for LocalLens.

Usage (from independent AI container): python /opt/ai/scan.py --limit 150
Only owners who opted into face analysis have face vectors created.
"""
import argparse
import logging
import os
import time
import threading
from pathlib import Path

import mysql.connector
import numpy as np
import torch
import open_clip
import cv2
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
LOG=logging.getLogger('locallens-ai')
torch.set_num_threads(int(os.getenv('AI_THREADS', '2')))

# These are approximate visual concepts, not guaranteed detections.
CONCEPTS = {
  'cat': 'a clear photograph of a domestic cat',
  'dog': 'a clear photograph of a dog',
  'bird': 'a photograph of a bird',
  'horse': 'a photograph of a horse',
  'fish': 'a photograph of a fish',
  'wildlife': 'a photograph of a wild animal in nature',
  'car': 'a photograph of a passenger car',
  'truck': 'a photograph of a pickup truck',
  'motorcycle': 'a photograph of a motorcycle',
  'airplane': 'a photograph of an airplane',
  'boat': 'a photograph of a boat',
  'bicycle': 'a photograph of a bicycle',
  'christmas': 'a photo of Christmas decorations, a decorated tree and presents',
  'halloween': 'a photo of Halloween costumes, pumpkins or jack o lanterns',
  'thanksgiving': 'a photo of a Thanksgiving turkey dinner and fall decorations',
  'easter': 'a photo of Easter eggs and Easter decorations',
  'birthday': 'a birthday celebration with a birthday cake and candles',
  'new-year': 'a New Year celebration with party decorations and fireworks',
  'valentines-day': 'Valentines Day decorations, hearts and red roses',
  'fourth-of-july': 'Fourth of July American flag decorations and fireworks',
}


def get_db():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST','db'), port=int(os.getenv('DB_PORT','3306')),
        user=os.getenv('DB_USER','locallens'), password=os.environ['DB_PASSWORD'],
        database=os.getenv('DB_NAME','locallens'), connection_timeout=10)


def valid_original(owner, recorded):
    root=(Path(os.getenv('MEDIA_ROOT','/storage'))/'users'/str(owner)/'originals').resolve()
    path=Path(recorded).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise FileNotFoundError('Original not available in owner storage')
    return path


def create_clip():
    model,_,transform=open_clip.create_model_and_transforms('ViT-B-32',pretrained='laion2b_s34b_b79k',device='cpu')
    model.eval()
    tokens=open_clip.get_tokenizer('ViT-B-32')(list(CONCEPTS.values()))
    with torch.inference_mode():
        texts=model.encode_text(tokens)
        texts=texts/texts.norm(dim=-1,keepdim=True)
    return model,transform,texts


def classify(img, model, transform, texts):
    with torch.inference_mode():
        data=transform(img).unsqueeze(0)
        features=model.encode_image(data)
        features=features/features.norm(dim=-1,keepdim=True)
        scores=(features@texts.T).squeeze(0).cpu().tolist()
    tags=sorted(zip(CONCEPTS.keys(),scores),key=lambda pair:pair[1],reverse=True)
    # Conservative preliminary suggestions: these cosine scores are NOT probabilities.
    return [(name,round(float(score),4)) for name,score in tags if score>=0.27][:5]


def load_face_models():
    from huggingface_hub import hf_hub_download
    yu=hf_hub_download('opencv/face_detection_yunet','face_detection_yunet_2023mar.onnx')
    sf=hf_hub_download('opencv/face_recognition_sface','face_recognition_sface_2021dec.onnx')
    detector=cv2.FaceDetectorYN.create(yu,'',(320,320),score_threshold=0.82,nms_threshold=0.3,top_k=100)
    recognizer=cv2.FaceRecognizerSF.create(sf,'')
    return detector, recognizer


def find_faces(image, detector, recognizer):
    # Use a preview large enough for small faces; preserve normalized coordinates.
    image.thumbnail((2048, 2048))
    bgr = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]
    detector.setInputSize((width, height))
    _, faces = detector.detect(bgr)
    found = []
    for idx, row in enumerate(faces if faces is not None else []):
        x, y, fw, fh = (float(v) for v in row[:4])
        if fw < 22 or fh < 22:
            continue
        aligned = recognizer.alignCrop(bgr, row)
        vector = recognizer.feature(aligned).astype('float32').ravel()
        vector /= max(float(np.linalg.norm(vector)), 1e-9)
        found.append((idx, max(0, x/width), max(0, y/height),
                      min(1, fw/width), min(1, fh/height), vector))
    return found


def face_match(cur, user_id, emb):
    # Only human-confirmed labels can train subsequent automatic assignments.
    # A confirmed example can auto-name a clear best match; competing identities stay suggestions.
    cur.execute('''SELECT f.embedding, f.person_id, f.photo_id FROM ai_faces f
        WHERE f.user_id=%s AND f.person_id IS NOT NULL
          AND f.assignment_source='confirmed'
        ORDER BY f.id DESC LIMIT 1200''', (user_id,))
    scores = {}
    examples = {}
    for row in cur.fetchall():
        source = np.frombuffer(row['embedding'], dtype=np.float32)
        if source.shape != emb.shape:
            continue
        similarity = float(emb @ source / max(float(np.linalg.norm(source)), 1e-9))
        pid = row['person_id']
        scores[pid] = max(scores.get(pid, -1), similarity)
        examples.setdefault(pid, set()).add(row['photo_id'])
    if not scores:
        return None, None, False
    ranked = sorted(scores.items(), key=lambda it: it[1], reverse=True)
    person_id, best = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
    if best < 0.50:
        return None, None, False
    # A known name is assigned when its confirmed embedding leads by a clear margin.
    # Never train on automatic assignments; conflicting identities remain suggestions.
    auto = (best >= 0.50 and best - runner_up >= 0.08
            and len(examples[person_id]) >= 1)
    return person_id, best, auto


def candidates(conn, user_id, limit):
    cur = conn.cursor(dictionary=True)
    try:
        where = 'AND p.user_id=%s' if user_id else ''
        args = ([user_id] if user_id else []) + [limit]
        cur.execute(f'''SELECT p.id, p.user_id, p.storage_path,
            COALESCE(s.tags_done,0) AS tags_done,
            COALESCE(s.faces_done,0) AS faces_done,
            COALESCE(settings.enabled,0) AS faces_enabled
            FROM photos p
            LEFT JOIN ai_scans s ON s.photo_id=p.id
            LEFT JOIN ai_face_settings settings ON settings.user_id=p.user_id
            LEFT JOIN ai_index_failures fail ON fail.photo_id=p.id AND fail.user_id=p.user_id
            WHERE p.deleted_at IS NULL AND COALESCE(p.media_type,'photo')<>'video'
            {where} AND (s.photo_id IS NULL OR s.tags_done=0 OR
                        (settings.enabled=1 AND s.faces_done=0))
            AND (fail.photo_id IS NULL OR
                 (fail.attempts < 5 AND fail.retry_after <= NOW()))
            ORDER BY p.id ASC LIMIT %s''', args)
        return cur.fetchall()
    finally:
        cur.close()


def scan_one(conn, row, model, transform, texts, face_models):
    uid, pid = row['user_id'], row['id']
    cur = conn.cursor(dictionary=True)
    try:
        path = valid_original(uid, row['storage_path'])
        with Image.open(path) as opened:
            img = ImageOps.exif_transpose(opened).convert('RGB')
        tags_done = int(row['tags_done'])
        if not tags_done:
            labels = classify(img, model, transform, texts)
            # Serialize scan output with foreground edits. The model runs before
            # this short transaction; editing tags never waits for inference.
            cur.execute('SELECT id FROM photos WHERE id=%s AND user_id=%s FOR UPDATE', (pid,uid))
            if not cur.fetchone():
                raise RuntimeError('Photo no longer exists')
            cur.execute('''SELECT tag,action FROM ai_tag_feedback
                WHERE user_id=%s AND photo_id=%s''', (uid,pid))
            feedback = {r['tag']:r['action'] for r in cur.fetchall()}
            labels = [(tag,score) for tag,score in labels if feedback.get(tag) != 'reject']
            cur.execute('DELETE FROM ai_tags WHERE photo_id=%s AND user_id=%s', (pid,uid))
            if labels:
                cur.executemany('''INSERT INTO ai_tags(photo_id,user_id,tag,score)
                    VALUES (%s,%s,%s,%s)''', [(pid,uid,name,score) for name,score in labels])
            manual = [tag for tag,action in feedback.items() if action == 'add']
            if manual:
                cur.executemany('''INSERT INTO ai_tags(photo_id,user_id,tag,score)
                    VALUES (%s,%s,%s,1.0)
                    ON DUPLICATE KEY UPDATE score=1.0''',
                    [(pid,uid,tag) for tag in manual])
            tags_done = 1
        faces_done = int(row['faces_done'])
        if row['faces_enabled'] and not faces_done:
            if face_models is None:
                raise RuntimeError('Face models not available')
            detector, recognizer = face_models
            detected = find_faces(img, detector, recognizer)
            # If the owner withdrew consent during inference, don't retain vectors.
            cur.execute('SELECT enabled FROM ai_face_settings WHERE user_id=%s FOR UPDATE', (uid,))
            still_enabled = bool((cur.fetchone() or {}).get('enabled'))
            if still_enabled:
                # Retain human-confirmed names even on re-index; avoid clearing
                # manually reviewed faces as part of an automatic retry.
                cur.execute('SELECT COUNT(*) AS count FROM ai_faces WHERE photo_id=%s AND user_id=%s', (pid,uid))
                existing_count = cur.fetchone()['count']
                if existing_count == 0:
                    for idx, x, y, w, h, vector in detected:
                        possible, similarity, auto = face_match(cur, uid, vector)
                        cur.execute('''INSERT INTO ai_faces
                          (user_id,photo_id,face_index,x,y,w,h,embedding,
                           person_id,suggested_person_id,similarity,assignment_source)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                          (uid,pid,idx,x,y,w,h,vector.tobytes(),
                           possible if auto else None,
                           None if auto else possible, similarity,
                           'automatic' if auto else 'unassigned'))
                    LOG.info('Photo ID %s: detected %s face(s)', pid, len(detected))
                else:
                    LOG.info('Photo ID %s: retaining %s existing reviewed face(s)', pid, existing_count)
            faces_done = int(still_enabled)
        cur.execute('''INSERT INTO ai_scans(photo_id,user_id,tags_done,faces_done,error_message,scanned_at)
            VALUES (%s,%s,%s,%s,NULL,NOW()) ON DUPLICATE KEY UPDATE
            tags_done=VALUES(tags_done), faces_done=VALUES(faces_done),
            error_message=NULL, scanned_at=NOW()''', (pid,uid,tags_done,faces_done))
        cur.execute('DELETE FROM ai_index_failures WHERE photo_id=%s AND user_id=%s', (pid,uid))
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        LOG.warning('Photo ID %s indexing failed: %s', pid, str(exc)[:180])
        try:
            # Crucial: never set tags_done=1/faces_done=1 after an exception.
            # Failed images remain eligible once retry_after expires.
            cur.execute('''INSERT INTO ai_scans
                (photo_id,user_id,tags_done,faces_done,error_message,scanned_at)
                VALUES (%s,%s,%s,%s,%s,NOW()) ON DUPLICATE KEY UPDATE
                error_message=VALUES(error_message),scanned_at=NOW()''',
                (pid,uid,int(row['tags_done']),int(row['faces_done']),str(exc)[:250]))
            cur.execute('''INSERT INTO ai_index_failures
                (photo_id,user_id,attempts,last_error,retry_after)
                VALUES (%s,%s,1,%s,DATE_ADD(NOW(),INTERVAL 5 MINUTE))
                ON DUPLICATE KEY UPDATE attempts=attempts+1,
                last_error=VALUES(last_error),
                retry_after=DATE_ADD(NOW(),INTERVAL LEAST(1440,5*POW(3,LEAST(attempts,6))) MINUTE)''',
                (pid,uid,str(exc)[:500]))
            conn.commit()
        except Exception:
            conn.rollback()
            LOG.exception('Failed to record photo indexing error')
        return False
    finally:
        cur.close()


class ScanJob:
    """Tracks a CLI worker in MySQL; heartbeat uses its own database connection."""
    def __init__(self, conn, scope_user_id, total):
        self.conn = conn
        self.stop_event = threading.Event()
        self.total = total
        self.closed = False
        cur = conn.cursor()
        try:
            cur.execute("""INSERT INTO ai_scan_jobs
                (scope_user_id,state,batch_total,batch_processed,batch_success)
                VALUES (%s,'starting',%s,0,0)""", (scope_user_id or None, total))
            self.job_id = cur.lastrowid
            conn.commit()
        finally:
            cur.close()
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()

    def _heartbeat(self):
        # Separate DB connection: mysql.connector connections are not thread-safe.
        while not self.stop_event.wait(12):
            try:
                heartbeat_conn = get_db()
                try:
                    cur = heartbeat_conn.cursor()
                    try:
                        cur.execute("""UPDATE ai_scan_jobs SET heartbeat_at=NOW()
                            WHERE id=%s AND state IN ('starting','running')""", (self.job_id,))
                        heartbeat_conn.commit()
                    finally:
                        cur.close()
                finally:
                    heartbeat_conn.close()
            except Exception as exc:
                LOG.warning('AI scan heartbeat failed: %s', str(exc)[:120])

    def progress(self, processed, success):
        cur = self.conn.cursor()
        try:
            cur.execute("""UPDATE ai_scan_jobs SET state='running',
                batch_processed=%s, batch_success=%s, heartbeat_at=NOW()
                WHERE id=%s""", (processed,success,self.job_id))
            self.conn.commit()
        finally:
            cur.close()

    def finish(self, state, message=None):
        if self.closed:
            return
        self.closed = True
        self.stop_event.set()
        cur = self.conn.cursor()
        try:
            cur.execute("""UPDATE ai_scan_jobs SET state=%s,
                error_message=%s, heartbeat_at=NOW(), finished_at=NOW()
                WHERE id=%s""", (state, (message or '')[:500] or None, self.job_id))
            self.conn.commit()
        finally:
            cur.close()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--limit',type=int,default=100,help='Max images this invocation (default 100)')
    parser.add_argument('--user-id',type=int,default=0)
    parser.add_argument('--pause',type=float,default=1.0,help='Seconds between scans to reduce CPU pressure')
    args=parser.parse_args()
    if not 1<=args.limit<=100000: parser.error('limit must be 1..100000')
    conn=get_db()
    lock_cur=conn.cursor()
    lock_cur.execute("SELECT GET_LOCK('locallens_ai_indexing',0)")
    if lock_cur.fetchone()[0] != 1:
        lock_cur.close()
        conn.close()
        raise RuntimeError('AI indexer already active; use Photos to pause/resume')
    lock_cur.close()
    job=None
    try:
        # Before loading large AI models, create the job so the UI shows Starting.
        batch=candidates(conn,args.user_id,args.limit)
        job=ScanJob(conn,args.user_id,len(batch))
        if not batch:
            LOG.info('No new files to index')
            job.finish('completed')
            return
        LOG.info('Found %d photos to index (CPU worker only)',len(batch))
        model,transform,texts=create_clip()
        faces=None
        if any(row['faces_enabled'] and not row['faces_done'] for row in batch):
            faces=load_face_models()
        success=0
        job.progress(0,0)
        for num,row in enumerate(batch,1):
            if scan_one(conn,row,model,transform,texts,faces): success+=1
            job.progress(num,success)
            if num%10==0 or num==len(batch): LOG.info('Indexed %d/%d (%d success)',num,len(batch),success)
            if num<len(batch): time.sleep(max(0,args.pause))
        job.finish('completed')
    except Exception as exc:
        LOG.exception('AI indexing batch failed')
        if job is not None:
            try: job.finish('failed',str(exc))
            except Exception: LOG.exception('Could not save failed scan status')
        raise
    finally:
        if job is not None: job.stop_event.set()
        try:
            cur=conn.cursor()
            cur.execute("SELECT RELEASE_LOCK('locallens_ai_indexing')")
            cur.close()
        except Exception:
            pass
        conn.close()

if __name__=='__main__':main()
