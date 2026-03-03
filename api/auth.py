"""JWT authentication and RBAC helpers."""

import jwt
import functools
from datetime import datetime, timedelta, timezone
from flask import request, jsonify, g
from config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_HOURS


def generate_token(user_id: int, role: str = "admin") -> str:
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def require_auth(f):
    """Decorator: require valid JWT in Authorization header."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth_header[7:]
        try:
            payload = decode_token(token)
            g.user_id = payload["user_id"]
            g.user_role = payload.get("role", "viewer")
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return wrapper


def require_role(*roles):
    """Decorator: require user to have one of the specified roles."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if g.get("user_role") not in roles:
                return jsonify({"error": "Insufficient permissions"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator
