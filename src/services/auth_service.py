import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from threading import Lock

from src.database import database_connection
PERMISSIONS = ("view_history","acknowledge_alert","resolve_alert","manage_cameras","manage_persons","manage_users")

class AuthenticationError(Exception): pass
class InactiveAccountError(Exception): pass

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16); iterations = 210_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"

def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded: return False
    try:
        _, iterations, salt, expected = encoded.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError): return False

class AuthService:
    def __init__(self): self._sessions = {}; self._lock = Lock()
    def login(self, identity: str, password: str, remember: bool):
        with database_connection() as connection:
            user = connection.execute("SELECT * FROM users WHERE lower(email)=lower(?)", (identity.strip(),)).fetchone()
            if not user or not verify_password(password, user["password_hash"]): raise AuthenticationError()
            if not user["is_active"]: raise InactiveAccountError()
            token = secrets.token_urlsafe(48); expires = datetime.now(timezone.utc) + timedelta(days=30 if remember else 1)
            with self._lock: self._sessions[token] = (user["id"], expires)
            return token, self._serialize(connection, user)
    def authenticate(self, token: str | None):
        if not token: raise AuthenticationError()
        with self._lock: session = self._sessions.get(token)
        if not session or session[1] <= datetime.now(timezone.utc): raise AuthenticationError()
        with database_connection() as connection:
            user = connection.execute("SELECT * FROM users WHERE id=?", (session[0],)).fetchone()
            if not user: raise AuthenticationError()
            if not user["is_active"]: raise InactiveAccountError()
            return self._serialize(connection, user)
    def logout(self, token):
        with self._lock: self._sessions.pop(token, None)
    def change_password(self, user_id: str, password: str):
        with database_connection() as connection:
            connection.execute("UPDATE users SET password_hash=?,force_password_change=0,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (hash_password(password), user_id))
            return self._serialize(connection, connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
    @staticmethod
    def allowed(user, permission): return user["role"] == "admin" or bool(user["permissions"].get(permission))
    @staticmethod
    def _serialize(connection, user):
        permissions = {key: user["role"] == "admin" for key in PERMISSIONS}
        if user["role"] != "admin": permissions.update({r["permission_key"]: bool(r["is_granted"]) for r in connection.execute("SELECT permission_key,is_granted FROM user_permissions WHERE user_id=?", (user["id"],))})
        return {"id":user["id"],"email":user["email"],"name":user["display_name"],"role":user["role"],"active":bool(user["is_active"]),"force_password_change":bool(user["force_password_change"]),"permissions":permissions}

auth_service = AuthService()
