import hashlib
from fastapi import HTTPException


def throttle(get_connection, request, scope, limit, seconds, identity=None):
    # Do not trust client-supplied forwarding headers.
    identity = identity if identity is not None else (request.client.host if request.client else 'unknown')
    key = hashlib.sha256(f'{scope}:{identity}'.encode()).hexdigest()
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('INSERT INTO auth_limits (bucket_key, hits, reset_at) VALUES (%s, 0, UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE bucket_key=bucket_key', (key,))
        cursor.execute('SELECT hits, reset_at <= UTC_TIMESTAMP() AS expired, GREATEST(1, TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), reset_at)) AS remaining FROM auth_limits WHERE bucket_key=%s FOR UPDATE', (key,))
        row = cursor.fetchone()
        if row['expired']:
            cursor.execute('UPDATE auth_limits SET hits=1, reset_at=TIMESTAMPADD(SECOND, %s, UTC_TIMESTAMP()) WHERE bucket_key=%s', (seconds, key))
        elif row['hits'] >= limit:
            conn.commit()
            raise HTTPException(429, 'Too many attempts. Try again later.', headers={'Retry-After': str(row['remaining'])})
        else:
            cursor.execute('UPDATE auth_limits SET hits=hits+1 WHERE bucket_key=%s', (key,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def audit(cursor, event, actor=None, target=None):
    cursor.execute('INSERT INTO auth_audit (event_type, actor_id, target_id) VALUES (%s,%s,%s)', (event, actor, target))


from contextlib import contextmanager

@contextmanager
def database(get_connection):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        yield conn, cursor
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
