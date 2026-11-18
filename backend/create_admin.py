
from getpass import getpass

from main import get_connection
from security import hash_password


def create_admin():

    print("\n==============================")
    print(" LocalLens Administrator Setup")
    print("==============================\n")

    username = input("Username: ").strip()
    email = input("Email: ").strip().lower()
    display_name = input("Display name: ").strip()

    if not username or len(username) > 50:
        print("Username must contain 1-50 characters.")
        return

    if not email or "@" not in email or len(email) > 255:
        print("Invalid email address.")
        return

    if len(display_name) > 100:
        print("Display name is too long.")
        return

    password = getpass("Password: ")
    confirmation = getpass("Confirm password: ")

    if password != confirmation:
        print("Passwords do not match.")
        return

    if not 12 <= len(password) <= 128:
        print("Password must contain 12-128 characters.")
        return

    hashed = hash_password(password)

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT id FROM users
            WHERE username = %s OR email = %s
            LIMIT 1
            """,
            (username, email)
        )

        if cursor.fetchone():
            print("Username or email already exists.")
            return

        cursor.execute(
            """
            INSERT INTO users (
                username,
                email,
                password_hash,
                display_name,
                role,
                is_active
            )
            VALUES (%s, %s, %s, %s, 'admin', TRUE)
            """,
            (
                username,
                email,
                hashed,
                display_name or username
            )
        )

        conn.commit()

        print("\nAdministrator created successfully.")
        print(f"User ID: {cursor.lastrowid}")
        print(f"Username: {username}")
        print("Role: admin")

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    create_admin()
