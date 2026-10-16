"""用户明确选择的独立密码凭据；身份仍使用现有 users 表。"""
import hashlib
import hmac
import secrets
import time
from contextlib import aclosing, asynccontextmanager

from fastapi import HTTPException, Request
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError

from core.database import get_db
from models.auth import User
from models.demo_credentials import Demo_credentials
from models.demo_sessions import Demo_sessions
from models.demo_auth_limits import Demo_auth_limits
from schemas.auth import UserResponse

COOKIE_NAME = "demo_session"
SESSION_SECONDS = 86400
ITERATIONS = 600000


async def auth_db():
    try:
        async with aclosing(get_db()) as sessions:
            async for db in sessions:
                yield db
    except SQLAlchemyError:
        # 不记录SQL异常或参数，避免凭据进入日志。
        raise HTTPException(503, "账号服务暂时不可用，请稍后重试。") from None


@asynccontextmanager
async def safe_transaction(db):
    try:
        yield
    except SQLAlchemyError:
        try:
            await db.rollback()
        except SQLAlchemyError:
            pass
        raise HTTPException(503, "账号服务暂时不可用，请稍后重试。") from None


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password):
    salt = secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${value}"


def verify_password(password, encoded):
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or int(rounds) != ITERATIONS:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


async def lock_key(db, key):
    value = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": value})


async def throttle(db, email):
    now = int(time.time())
    async with safe_transaction(db):
        # 固定全局锁使多worker下计数原子化；限制先于密码运算。
        await lock_key(db, "demo-auth-rate")
        await db.execute(delete(Demo_auth_limits).where(Demo_auth_limits.window_epoch < now - 900))
        for label, maximum in (("global", 200), ("email:" + email, 10)):
            key = digest(label)
            row = await db.scalar(select(Demo_auth_limits).where(Demo_auth_limits.bucket_key == key))
            if row is None:
                row = Demo_auth_limits(bucket_key=key, window_epoch=now, attempts=0)
                db.add(row)
            if row.attempts >= maximum:
                await db.commit()
                raise HTTPException(429, "尝试次数过多，请15分钟后再试。", headers={"Retry-After": "900"})
            row.attempts += 1
        await db.commit()


def require_demo_request(request: Request):
    # 浏览器跨站表单不能设置该头；不为此接口开放跨域。
    if request.headers.get("x-demo-auth") != "1":
        raise HTTPException(403, "请通过本站账号页面操作。")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "不允许跨站账号请求。")


def set_session_cookie(response, token):
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, secure=True, httponly=True, samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"


async def create_session(db, user):
    token = secrets.token_urlsafe(32)
    await db.execute(delete(Demo_sessions).where(Demo_sessions.expires_epoch <= int(time.time())))
    db.add(Demo_sessions(owner_key=user.id, session_digest=digest(token), expires_epoch=int(time.time()) + SESSION_SECONDS))
    return token


async def resolve_demo_user(request, db):
    token = request.cookies.get(COOKIE_NAME)
    if not token or len(token) > 128:
        raise HTTPException(401, "登录已失效，请重新登录。")
    async with safe_transaction(db):
        row = await db.scalar(select(Demo_sessions).where(Demo_sessions.session_digest == digest(token), Demo_sessions.expires_epoch > int(time.time())))
        user = await db.get(User, row.owner_key) if row else None
        if user is None or not user.id.startswith("demo:"):
            raise HTTPException(401, "登录已失效，请重新登录。")
        return UserResponse(id=user.id, email=user.email, name=user.name, role="user", last_login=user.last_login)
