"""独立Demo账号API，不使用平台协作者身份注册。"""
import asyncio
import json
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, SecretStr, ValidationError, field_validator
from sqlalchemy import delete, select

from models.auth import User
from models.demo_credentials import Demo_credentials
from models.demo_sessions import Demo_sessions
from services.demo_auth import (
    COOKIE_NAME, auth_db, create_session, digest, hash_password, lock_key,
    require_demo_request, resolve_demo_user, safe_transaction, set_session_cookie,
    throttle, verify_password,
)

router = APIRouter(prefix="/api/v1/demo-auth", tags=["demo-auth"])


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: SecretStr

    @field_validator("password")
    @classmethod
    def check_password(cls, value):
        if not 10 <= len(value.get_secret_value()) <= 128:
            raise ValueError("密码需要10到128个字符")
        return value


async def read_credentials(request):
    require_demo_request(request)
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 4096:
            raise HTTPException(413, "账号请求内容过大。")
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        return Credentials.model_validate(json.loads(body))
    except (ValidationError, ValueError, TypeError):
        # 不返回默认验证详情，其中可能含有密码原文。
        raise HTTPException(422, "请填写有效邮箱及10到128个字符的密码。") from None


@router.post("/register", status_code=201)
async def register(request: Request, response: Response, db=Depends(auth_db)):
    data = await read_credentials(request)
    email = str(data.email).lower()
    await throttle(db, email)
    encoded = await asyncio.to_thread(hash_password, data.password.get_secret_value())
    async with safe_transaction(db):
        await lock_key(db, "demo-email:" + email)
        if await db.scalar(select(Demo_credentials.id).where(Demo_credentials.email_key == email)):
            raise HTTPException(409, "这个邮箱已注册Demo账号，请使用邮箱登录。")
        # 与平台主体隔离；不按相同邮箱关联原用户。
        user = User(id="demo:" + secrets.token_hex(24), email=email, name=None, role="user", last_login=datetime.now(timezone.utc))
        db.add(user)
        await db.flush()
        db.add(Demo_credentials(owner_key=user.id, email_key=email, password_digest=encoded))
        token = await create_session(db, user)
        await db.commit()
    set_session_cookie(response, token)
    return {"authenticated": True, "email_verified": False, "message": "账号已创建并登录；本Demo暂不发送邮箱验证邮件。"}


@router.post("/login")
async def login(request: Request, response: Response, db=Depends(auth_db)):
    data = await read_credentials(request)
    email = str(data.email).lower()
    await throttle(db, email)
    async with safe_transaction(db):
        row = await db.scalar(select(Demo_credentials).where(Demo_credentials.email_key == email))
        encoded = row.password_digest if row else None
        owner = row.owner_key if row else None
        await db.commit()
    password = data.password.get_secret_value()
    if encoded is None:
        # 不存在用户也执行同等成本运算。
        await asyncio.to_thread(hash_password, password)
        raise HTTPException(401, "邮箱或密码不正确。")
    if not await asyncio.to_thread(verify_password, password, encoded):
        raise HTTPException(401, "邮箱或密码不正确。")
    async with safe_transaction(db):
        user = await db.get(User, owner)
        if user is None or not owner.startswith("demo:"):
            raise HTTPException(401, "邮箱或密码不正确。")
        user.last_login = datetime.now(timezone.utc)
        old_token = request.cookies.get(COOKIE_NAME)
        if old_token:
            await db.execute(delete(Demo_sessions).where(Demo_sessions.session_digest == digest(old_token)))
        token = await create_session(db, user)
        await db.commit()
    set_session_cookie(response, token)
    return {"authenticated": True, "email_verified": False}


@router.get("/me")
async def me(request: Request, response: Response, db=Depends(auth_db)):
    require_demo_request(request)
    await resolve_demo_user(request, db)
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True, "email_verified": False}


@router.post("/logout")
async def logout(request: Request, response: Response, db=Depends(auth_db)):
    require_demo_request(request)
    token = request.cookies.get(COOKIE_NAME)
    async with safe_transaction(db):
        if token:
            await db.execute(delete(Demo_sessions).where(Demo_sessions.session_digest == digest(token)))
        await db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return {"logged_out": True}
