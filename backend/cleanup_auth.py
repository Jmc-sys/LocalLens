from main import get_connection

def main():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM auth_sessions WHERE expires_at <= UTC_TIMESTAMP()')
        cursor.execute('DELETE FROM auth_limits WHERE reset_at <= UTC_TIMESTAMP()')
        cursor.execute('DELETE FROM auth_audit WHERE created_at < UTC_TIMESTAMP() - INTERVAL 90 DAY')
        conn.commit()
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    main()
