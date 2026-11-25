"""Singleton Family Group backed by existing Shared Albums membership.

The family album contains references, never duplicate originals. Adding/removing
members is an administrator-only action; removal revokes album access and unshares
that user's contributed items without deleting original media.
"""
from fastapi import HTTPException
from guard import database

SETTING_KEY = 'family_shared_album_id'


def _family_album_id(cursor, lock=False):
    cursor.execute('SELECT setting_value FROM system_settings WHERE setting_key=%s' +
                   (' FOR UPDATE' if lock else ''), (SETTING_KEY,))
    row = cursor.fetchone()
    if row and row['setting_value']:
        try:
            return int(row['setting_value'])
        except (ValueError, TypeError):
            raise HTTPException(500, 'Invalid Family Group configuration')
    return None


def annotate_family_members(get_connection, users):
    """Adds the family status to each admin Manage Users row in two small queries."""
    if not users:
        return users
    with database(get_connection) as (_, cursor):
        album_id = _family_album_id(cursor)
        member_ids = set()
        if album_id:
            cursor.execute('SELECT user_id FROM shared_album_members WHERE album_id=%s', (album_id,))
            member_ids = {row['user_id'] for row in cursor.fetchall()}
    for user in users:
        user['family_member'] = user['id'] in member_ids
    return users


def set_family_membership(get_connection, admin_id, target_id, enabled):
    with database(get_connection) as (conn, cursor):
        # This insert creates one serialized row; FOR UPDATE prevents two admins
        # from creating distinct Family Albums concurrently.
        cursor.execute('''INSERT IGNORE INTO system_settings
            (setting_key,setting_value,description)
            VALUES(%s,'','Shared album ID for the one Family Group')''', (SETTING_KEY,))
        album_id = _family_album_id(cursor, lock=True)
        cursor.execute('SELECT id,is_active FROM users WHERE id=%s FOR UPDATE', (target_id,))
        target = cursor.fetchone()
        if not target:
            raise HTTPException(404, 'User not found')
        if enabled and not target['is_active']:
            raise HTTPException(409, 'Disabled users cannot join the Family Group')
        if enabled and not album_id:
            cursor.execute('''INSERT INTO shared_albums(name,description,created_by)
                VALUES(%s,%s,%s)''',
                ('Family Album', 'Photos and videos contributed by family members', admin_id))
            album_id = cursor.lastrowid
            cursor.execute('UPDATE system_settings SET setting_value=%s WHERE setting_key=%s',
                           (str(album_id), SETTING_KEY))
        if enabled:
            cursor.execute('''INSERT IGNORE INTO shared_album_members(album_id,user_id)
                VALUES(%s,%s)''', (album_id, target_id))
        elif album_id:
            # Revocation also removes that account's contributions from sharing.
            # Their originals, albums and trash remain fully untouched.
            cursor.execute('''DELETE i FROM shared_album_items i
                INNER JOIN photos p ON p.id=i.photo_id
                WHERE i.album_id=%s AND p.user_id=%s''', (album_id, target_id))
            cursor.execute('''DELETE FROM shared_album_members
                WHERE album_id=%s AND user_id=%s''', (album_id, target_id))
        conn.commit()
        return {'status': 'updated', 'family_member': bool(enabled), 'album_id': album_id}


def family_album_id_for_cursor(cursor):
    return _family_album_id(cursor)
