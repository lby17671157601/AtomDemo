"""真实数据库、真实Cookie会话；不覆盖身份依赖，不输出凭据。"""
import secrets
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from core.database import db_manager
from models.auth import User
from models.demo_credentials import Demo_credentials
from models.demo_sessions import Demo_sessions
from models.demo_auth_limits import Demo_auth_limits
from models.projects import Projects
from models.messages import Messages
from models.project_files import Project_files
from routers import demo_auth, demo_credentials, demo_sessions, demo_auth_limits, workspace, preview
from services.demo_auth import COOKIE_NAME, digest, hash_password, verify_password


class DemoAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FastAPI()
        for module in (demo_auth, demo_credentials, demo_sessions, demo_auth_limits, workspace, preview):
            self.app.include_router(module.router)
        self.emails = []
        self.password = secrets.token_urlsafe(24)
        self.clients = []
        self.client = self.new_client()

    def new_client(self):
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="https://test", headers={"X-Demo-Auth": "1"})
        self.clients.append(client)
        return client

    def email(self):
        value = "demo-test-" + secrets.token_hex(12) + "@example.com"
        self.emails.append(value)
        return value

    async def register(self, client=None):
        client = client or self.client
        email = self.email()
        response = await client.post("/api/v1/demo-auth/register", json={"email": email, "password": self.password})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["authenticated"], True)
        self.assertEqual(response.json()["email_verified"], False)
        self.assertNotIn(self.password, response.text)
        return email

    async def project(self, client=None):
        response = await (client or self.client).post("/api/v1/workspace/projects", json={"name": "独立认证临时测试"})
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    async def asyncTearDown(self):
        self.app.dependency_overrides.clear()
        async with db_manager.session() as db:
            owners = list(await db.scalars(select(Demo_credentials.owner_key).where(Demo_credentials.email_key.in_(self.emails))))
            # 失败注册也可能产生临时User；仅处理本测试的随机邮箱与demo前缀。
            owners += list(await db.scalars(select(User.id).where(User.email.in_(self.emails), User.id.like("demo:%"))))
            if owners:
                for model in (Messages, Project_files, Projects):
                    await db.execute(delete(model).where(model.user_id.in_(owners)))
                await db.execute(delete(Demo_sessions).where(Demo_sessions.owner_key.in_(owners)))
                await db.execute(delete(Demo_credentials).where(Demo_credentials.owner_key.in_(owners)))
                await db.execute(delete(User).where(User.id.in_(owners)))
            await db.execute(delete(Demo_auth_limits).where(Demo_auth_limits.bucket_key.in_([digest("email:" + email) for email in self.emails])))
            await db.commit()
        for client in self.clients:
            await client.aclose()
        await db_manager.close_db()

    async def test_register_crud_refresh_login_and_revoke(self):
        email = await self.register()
        token = self.client.cookies.get(COOKIE_NAME)
        cookie = next(item for item in self.client.cookies.jar if item.name == COOKIE_NAME)
        self.assertTrue(cookie.secure)
        self.assertIn("HttpOnly", cookie._rest)
        self.assertEqual(cookie._rest.get("SameSite"), "lax")
        pid = await self.project()
        root = f"/api/v1/workspace/projects/{pid}"
        self.assertEqual((await self.client.patch(root, json={"name": "独立账号重命名"})).status_code, 200)
        self.assertEqual((await self.client.post(root + "/messages", json={"content": "测试持久化，不调用模型"})).status_code, 201)
        for content in ("初次保存", "再次保存"):
            self.assertEqual((await self.client.put(root + "/files", json={"path": "a.txt", "content": content})).status_code, 200)
        fresh = self.new_client()
        fresh.cookies.update(self.client.cookies)
        self.assertEqual((await fresh.get("/api/v1/demo-auth/me")).status_code, 200)
        self.assertEqual((await fresh.get(root + "/messages")).json()["total"], 2)
        self.assertEqual((await fresh.get(root + "/files")).json()["items"][0]["content"], "再次保存")
        self.assertEqual((await self.client.post("/api/v1/demo-auth/logout")).status_code, 200)
        # 撤销后即便复制旧Cookie和平台Bearer也不能回落平台身份。
        for url in ("/api/v1/demo-auth/me", "/api/v1/workspace/projects"):
            self.assertEqual((await fresh.get(url, headers={"Authorization": "Bearer invalid"})).status_code, 401)
        self.assertEqual((await self.client.post("/api/v1/demo-auth/login", json={"email": email.upper(), "password": self.password})).status_code, 200)
        self.assertNotEqual(token, self.client.cookies.get(COOKIE_NAME))
        rows = (await self.client.get("/api/v1/workspace/projects")).json()["items"]
        self.assertEqual([row["id"] for row in rows], [pid])
        self.assertEqual((await self.client.delete(root)).status_code, 200)
        self.assertEqual((await self.client.get(root + "/files")).status_code, 404)
        async with db_manager.session() as db:
            credential = await db.scalar(select(Demo_credentials).where(Demo_credentials.email_key == email))
            self.assertTrue(credential.owner_key.startswith("demo:"))
            self.assertTrue(verify_password(self.password, credential.password_digest))
            session = await db.scalar(select(Demo_sessions).where(Demo_sessions.owner_key == credential.owner_key))
            self.assertEqual(session.session_digest, digest(self.client.cookies.get(COOKIE_NAME)))
            self.assertNotEqual(session.session_digest, self.client.cookies.get(COOKIE_NAME))
            for model in (Messages, Project_files):
                self.assertIsNone(await db.scalar(select(model.id).where(model.project_id == pid)))

    async def test_two_accounts_and_existing_project_isolation(self):
        await self.register()
        pid = await self.project()
        other = self.new_client()
        await self.register(other)
        self.assertEqual((await other.get("/api/v1/workspace/projects")).json()["total"], 0)
        for method, suffix, data in (
            ("GET", "/messages", None), ("GET", "/files", None),
            ("PATCH", "", {"name": "越权"}), ("DELETE", "", None),
            ("POST", "/messages", {"content": "越权"}),
            ("PUT", "/files", {"path": "a.txt", "content": "越权"}),
            ("POST", "/preview-check", {}), ("POST", "/generate", {"content": "越权"}),
        ):
            response = await other.request(method, f"/api/v1/workspace/projects/{pid}{suffix}", json=data)
            self.assertEqual(response.status_code, 404)
        async with db_manager.session() as db:
            existing = list(await db.scalars(select(Projects.id).where(Projects.name == "test01")))
        for old_id in existing:
            self.assertEqual((await self.client.get(f"/api/v1/workspace/projects/{old_id}/files")).status_code, 404)

    async def test_input_errors_duplicate_and_wrong_password_are_safe(self):
        email = await self.register()
        duplicate = await self.client.post("/api/v1/demo-auth/register", json={"email": email.upper(), "password": self.password})
        self.assertEqual(duplicate.status_code, 409)
        wrong = await self.client.post("/api/v1/demo-auth/login", json={"email": email, "password": secrets.token_urlsafe(24)})
        self.assertEqual(wrong.status_code, 401)
        missing_email = self.email()
        missing = await self.client.post("/api/v1/demo-auth/login", json={"email": missing_email, "password": self.password})
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json(), wrong.json())
        for payload in ({"email": email, "password": "short"}, {"email": "bad", "password": self.password}, {"email": email, "password": self.password, "role": "admin"}):
            response = await self.client.post("/api/v1/demo-auth/register", json=payload)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(self.password, response.text)
            self.assertNotIn('"input"', response.text)
        malformed = await self.client.post("/api/v1/demo-auth/login", content=b"{not-json")
        self.assertEqual(malformed.status_code, 422)
        large = await self.client.post("/api/v1/demo-auth/login", content=b"x" * 4097)
        self.assertEqual(large.status_code, 413)

    async def test_expiry_csrf_and_private_tables(self):
        await self.register()
        async with db_manager.session() as db:
            row = await db.scalar(select(Demo_sessions).where(Demo_sessions.session_digest == digest(self.client.cookies.get(COOKIE_NAME))))
            row.expires_epoch = int(time.time()) - 1
            await db.commit()
        self.assertEqual((await self.client.get("/api/v1/workspace/projects")).status_code, 401)
        self.assertEqual((await self.client.get("/api/v1/demo-auth/me", headers={"X-Demo-Auth": ""})).status_code, 403)
        self.assertEqual((await self.client.post("/api/v1/demo-auth/logout", headers={"Sec-Fetch-Site": "cross-site"})).status_code, 403)
        for name in ("demo_credentials", "demo_sessions", "demo_auth_limits"):
            for method in ("GET", "POST", "PATCH", "DELETE"):
                self.assertEqual((await self.client.request(method, f"/api/v1/entities/{name}", json={})).status_code, 404)

    async def test_throttle_before_password_work(self):
        email = self.email()
        async with db_manager.session() as db:
            db.add(Demo_auth_limits(bucket_key=digest("email:" + email), window_epoch=int(time.time()), attempts=10))
            await db.commit()
        with patch("routers.demo_auth.hash_password", side_effect=AssertionError("不应执行密码运算")):
            response = await self.client.post("/api/v1/demo-auth/register", json={"email": email, "password": self.password})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "900")

    async def test_database_failure_and_registration_rollback(self):
        email = self.email()
        # 在User已flush后触发SQL错误，验证整段注册回滚且不泄露参数。
        async def fail_session(db, user):
            raise OperationalError("测试故障", {"password": self.password}, RuntimeError("测试故障"))
        with patch("routers.demo_auth.create_session", side_effect=fail_session):
            response = await self.client.post("/api/v1/demo-auth/register", json={"email": email, "password": self.password})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(self.password, response.text)
        self.assertNotIn("password", response.text)
        async with db_manager.session() as db:
            self.assertIsNone(await db.scalar(select(Demo_credentials.id).where(Demo_credentials.email_key == email)))
            self.assertIsNone(await db.scalar(select(User.id).where(User.email == email)))

    def test_password_salt_and_verification(self):
        first = hash_password(self.password)
        second = hash_password(self.password)
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(self.password, first))
        self.assertFalse(verify_password("wrong-password", first))
        self.assertFalse(verify_password(self.password, "invalid"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
