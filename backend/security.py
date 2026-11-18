import os
import jwt

from datetime import datetime, timedelta, timezone
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from fastapi import HTTPException, status

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
)

if len(JWT_SECRET) < 64:
    raise RuntimeError("JWT_SECRET is too short.")

if JWT_ALGORITHM != "HS256":
    raise RuntimeError("Unsupported JWT algorithm.")

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hash.verify(password, hashed)
    except (UnknownHashError, ValueError):
        return False


def create_access_token(user_id: int, session_id: str) -> str:
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "jti": session_id,
        "iat": now,
        "exp": now + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        ),
        "iss": "locallens",
        "aud": "locallens-api",
        "type": "access"
    }

    return jwt.encode(
        payload,
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )


def decode_access_token(token: str) -> tuple[int, str]:
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            issuer="locallens",
            audience="locallens-api",
            options={
                "require": ["sub", "exp", "iat", "jti"]
            }
        )

        if payload.get("type") != "access":
            raise ValueError("Invalid token type")

        user_id = int(payload["sub"])

        if user_id <= 0:
            raise ValueError("Invalid user ID")

        session_id = payload["jti"]
        if not isinstance(session_id, str) or len(session_id) != 32:
            raise ValueError("Invalid session ID")
        return user_id, session_id

    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"}
        )
