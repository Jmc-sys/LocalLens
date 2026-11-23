"""Filename safety and same-name/different-content conflict inspection.

These helpers intentionally do NOT compare decoded pixels: equality is the
original-file SHA256. Same filename with a different SHA256 needs review.
"""
from pathlib import Path
from fastapi import HTTPException


def name_for_duplicate(name: str | None, original_name: str) -> str:
    """Require a distinct user-selected name while preserving media extension."""
    original = (original_name or 'media').replace('\\', '/').split('/')[-1]
    ext = Path(original).suffix
    raw = (name or '').strip()
    if not raw or '/' in raw or '\\' in raw or any(ord(ch) < 32 for ch in raw):
        raise HTTPException(422, 'Enter a valid filename for the new file')
    if len(raw) > 245:
        raise HTTPException(422, 'New filename is too long')
    supplied_ext = Path(raw).suffix
    if supplied_ext:
        if supplied_ext.casefold() != ext.casefold():
            raise HTTPException(422, f'Keep the original {ext} file extension')
    else:
        raw += ext
    if raw.casefold() == original.casefold():
        raise HTTPException(422, 'Choose a different name for the new file')
    return raw


def find_filename_collision(cursor, user_id: int, filename: str, sha256: str):
    """Return a conflicting owned record only if its BYTES are different.

    MySQL's normal filename collation is typically case insensitive. No cross-
    user information is returned. The caller decides what to do with trash.
    """
    cursor.execute('''SELECT id, original_filename, mime_type, media_type, deleted_at
        FROM photos
        WHERE user_id=%s AND original_filename=%s AND sha256<>%s
        ORDER BY (deleted_at IS NULL) DESC, id DESC LIMIT 1''',
        (user_id, filename, sha256))
    return cursor.fetchone()


def filename_collision_response(row):
    return {
        'status': 'name_conflict',
        'id': row['id'],
        'in_trash': bool(row['deleted_at']),
        'existing': {key: row[key] for key in
                     ('id', 'original_filename', 'mime_type', 'media_type')},
    }
