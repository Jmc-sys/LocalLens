"""Lossless Apple Live Photo motion resource attachment."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from photos import database

ROOT = Path(os.getenv('MEDIA_ROOT', '/storage')).resolve()
MAX_BYTES = int(os.getenv('MAX_UPLOAD_MB', '100')) * 1024**2
RESERVE = int(os.getenv('MIN_FREE_DISK_GB', '10')) * 1024**3


def run(args, timeout=30):
    try:
        return subprocess.run(args, check=True, capture_output=True, timeout=timeout).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        raise HTTPException(422, 'Unable to inspect or process media') from exc


def identifier(path, group):
    raw = run(['exiftool', '-j', '-G1', '-ContentIdentifier', '-MediaGroupUUID', str(path)])
    tags = json.loads(raw)[0]
    value = tags.get(f'{group}:ContentIdentifier') or tags.get(f'{group}:MediaGroupUUID')
    return str(value).strip().lower() if value else None


def safe_path(value, user_id):
    path = Path(value).resolve()
    if not path.is_relative_to(ROOT / 'users' / str(user_id)) or not path.is_file():
        raise HTTPException(404, 'Media file unavailable')
    return path


class StatusRequest(BaseModel):
    photo_ids: list[int] = Field(max_length=5000)


def build_live_router(get_connection, get_current_user):
    router = APIRouter(prefix='/api/live', tags=['Live Photos'])

    @router.post('/status')
    def status(data: StatusRequest, user=Depends(get_current_user)):
        if not data.photo_ids:
            return {'ids': []}
        marks = ','.join(['%s'] * len(data.photo_ids))
        with database(get_connection) as (conn, cur):
            cur.execute(f'''SELECT DISTINCT p.id FROM photos p JOIN photo_resources r ON r.photo_id=p.id
                        WHERE p.user_id=%s AND r.resource_type='live_video' AND p.id IN ({marks})''',
                        (user['id'], *data.photo_ids))
            attached = [r['id'] for r in cur.fetchall()]
            # This is evidence of an incomplete original Live Photo backup,
            # never proof that the missing motion clip was uploaded.
            cur.execute(f'''SELECT p.id FROM photos p
                WHERE p.user_id=%s AND p.id IN ({marks})
                AND p.content_identifier IS NOT NULL
                AND p.media_type <> 'video'
                AND NOT EXISTS(SELECT 1 FROM photo_resources r
                    WHERE r.photo_id=p.id AND r.resource_type='live_video')''',
                (user['id'], *data.photo_ids))
            missing = [r['id'] for r in cur.fetchall()]
            return {'ids': attached, 'missing_ids': missing}

    @router.post('/{photo_id}/motion')
    def attach(photo_id: int, file: UploadFile=File(...), user=Depends(get_current_user)):
        """Legacy explicit endpoint shares the same single-write attachment service."""
        from motion_service import stage_upload, attach_staged
        name = (file.filename or '').replace('\\', '/').split('/')[-1][:255]
        if not name.lower().endswith('.mov'):
            raise HTTPException(415, 'Choose an original MOV motion file')
        try:
            temp, size, sha256, motion_id = stage_upload(file, user['id'])
            try:
                return attach_staged(get_connection, user, photo_id, temp, name,
                                     size, sha256, motion_id, allow_filename=False)
            finally:
                temp.unlink(missing_ok=True)
        finally:
            file.file.close()

    def resource(photo_id, uid):
        with database(get_connection) as (conn,cur):
            cur.execute("""SELECT r.storage_path,r.original_filename FROM photo_resources r JOIN photos p ON p.id=r.photo_id
                         WHERE p.id=%s AND p.user_id=%s AND r.resource_type='live_video' LIMIT 1""", (photo_id, uid))
            row=cur.fetchone()
        if not row: raise HTTPException(404,'Live Photo motion not found')
        return row, safe_path(row['storage_path'],uid)

    @router.get('/{photo_id}/motion')
    def original(photo_id:int,user=Depends(get_current_user)):
        row,path=resource(photo_id,user['id'])
        return FileResponse(path,media_type='video/quicktime',filename=row['original_filename'],headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

    @router.get('/{photo_id}/originals')
    def originals(photo_id:int,user=Depends(get_current_user)):
        uid=user['id']; row,motion=resource(photo_id,uid)
        with database(get_connection) as (conn,cur):
            cur.execute('SELECT storage_path,original_filename FROM photos WHERE id=%s AND user_id=%s',(photo_id,uid))
            photo=cur.fetchone()
        if not photo: raise HTTPException(404,'Photo not found')
        still=safe_path(photo['storage_path'],uid)
        if shutil.disk_usage(ROOT).free < RESERVE + still.stat().st_size + motion.stat().st_size + 65536:
            raise HTTPException(507,'Insufficient server storage for archive')
        fd,filename=tempfile.mkstemp(suffix='.zip',dir=str(motion.parent)); os.close(fd)
        output=Path(filename)
        try:
            def basename(name): return name.replace(chr(92),'/').split('/')[-1]
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
                archive.write(still,basename(photo['original_filename']))
                archive.write(motion,basename(row['original_filename']))
            return FileResponse(output,media_type='application/zip',filename=f'LivePhoto-{photo_id}.zip',headers={'Cache-Control':'private, no-store'},background=BackgroundTask(output.unlink,missing_ok=True))
        except Exception:
            output.unlink(missing_ok=True); raise

    @router.get('/{photo_id}/preview')
    def preview(photo_id:int,user=Depends(get_current_user)):
        _,path=resource(photo_id,user['id'])
        if shutil.disk_usage(ROOT).free < RESERVE + MAX_BYTES:
            raise HTTPException(507,'Insufficient server storage for preview')
        fd, filename=tempfile.mkstemp(suffix='.mp4',dir=str(path.parent)); os.close(fd)
        output=Path(filename)
        try:
            run(['ffmpeg','-nostdin','-v','error','-y','-threads','2','-i',str(path),'-map','0:v:0','-map','0:a:0?','-vf',"scale='min(1280,iw)':-2",'-c:v','libx264','-threads','2','-pix_fmt','yuv420p','-preset','fast','-c:a','aac','-movflags','+faststart','-fs',str(MAX_BYTES),str(output)], timeout=60)
            return FileResponse(output,media_type='video/mp4',headers={'Cache-Control':'private, no-store'},background=BackgroundTask(output.unlink,missing_ok=True))
        except Exception:
            output.unlink(missing_ok=True); raise

    return router
