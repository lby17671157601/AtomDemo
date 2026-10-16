"""真实数据库集成测试；测试身份仅用于业务授权，不冒充官方认证验收。"""
import unittest
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from dependencies.auth import get_current_user
from routers import messages, project_files, projects, workspace
from schemas.auth import UserResponse


class WorkspaceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FastAPI()
        self.app.include_router(workspace.router)
        self.app.include_router(projects.router)
        self.app.include_router(messages.router)
        self.app.include_router(project_files.router)
        self.uid = f"integration-{uuid4()}"
        self.user = UserResponse(id=self.uid, email="")
        self.created = []
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")

    def as_user(self, uid):
        async def identity():
            return UserResponse(id=uid, email="")
        self.app.dependency_overrides[get_current_user] = identity

    async def new_project(self):
        self.as_user(self.uid)
        response = await self.client.post("/api/v1/workspace/projects", json={"name": "集成测试项目"})
        self.assertEqual(response.status_code, 201, response.text)
        row = response.json()
        self.created.append(row["id"])
        return row["id"]

    async def asyncTearDown(self):
        self.app.dependency_overrides.pop(workspace.workspace_db, None)
        self.as_user(self.uid)
        for pid in self.created:
            await self.client.delete(f"/api/v1/workspace/projects/{pid}")
        await self.client.aclose()
        from core.database import db_manager
        await db_manager.close_db()

    async def test_authentication_required_and_generic_routes_closed(self):
        response = await self.client.get("/api/v1/workspace/projects")
        self.assertEqual(response.status_code, 401)
        response = await self.client.get("/api/v1/workspace/projects", headers={"Authorization": "Bearer invalid"})
        self.assertEqual(response.status_code, 401)
        for entity in ("projects", "messages", "project_files"):
            response = await self.client.get(f"/api/v1/entities/{entity}/all")
            self.assertEqual(response.status_code, 404)

    async def test_project_messages_files_persist_across_requests(self):
        pid = await self.new_project()
        renamed = await self.client.patch(f"/api/v1/workspace/projects/{pid}", json={"name": "已重命名"})
        self.assertEqual(renamed.status_code, 200)
        sent = await self.client.post(f"/api/v1/workspace/projects/{pid}/messages", json={"content": "构建一个页面"})
        self.assertEqual(sent.status_code, 201, sent.text)
        self.assertEqual(len(sent.json()["items"]), 2)
        file = await self.client.put(f"/api/v1/workspace/projects/{pid}/files", json={"path": "src/App.tsx", "content": "测试文件内容，不执行"})
        self.assertEqual(file.status_code, 200, file.text)
        changed = await self.client.put(f"/api/v1/workspace/projects/{pid}/files", json={"path": "src/App.tsx", "content": "更新后的内容"})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(file.json()["id"], changed.json()["id"])
        # 每个 HTTP 请求由独立 get_db 会话处理，读取不是之前的内存对象。
        read = await self.client.get(f"/api/v1/workspace/projects/{pid}/messages")
        self.assertEqual(read.json()["total"], 2)
        self.assertEqual(read.json()["items"][0]["role"], "user")
        files = await self.client.get(f"/api/v1/workspace/projects/{pid}/files")
        self.assertEqual(files.json()["total"], 1)
        self.assertEqual(files.json()["items"][0]["content"], "更新后的内容")
        rows = (await self.client.get("/api/v1/workspace/projects")).json()["items"]
        self.assertEqual(next(row["name"] for row in rows if row["id"] == pid), "已重命名")

    async def test_other_user_cannot_access_or_mutate(self):
        pid = await self.new_project()
        self.as_user(f"other-{uuid4()}")
        rows = (await self.client.get("/api/v1/workspace/projects")).json()["items"]
        self.assertNotIn(pid, [row["id"] for row in rows])
        calls = [
            ("GET", f"/projects/{pid}/messages", None),
            ("GET", f"/projects/{pid}/files", None),
            ("PATCH", f"/projects/{pid}", {"name": "越权"}),
            ("DELETE", f"/projects/{pid}", None),
            ("POST", f"/projects/{pid}/messages", {"content": "越权"}),
            ("PUT", f"/projects/{pid}/files", {"path": "a.txt", "content": "越权"}),
        ]
        for method, path, data in calls:
            response = await self.client.request(method, f"/api/v1/workspace{path}", json=data)
            self.assertEqual(response.status_code, 404, (method, response.text))

    async def test_atomic_delete_cleans_children(self):
        pid = await self.new_project()
        await self.client.post(f"/api/v1/workspace/projects/{pid}/messages", json={"content": "待删除"})
        await self.client.put(f"/api/v1/workspace/projects/{pid}/files", json={"path": "a.txt", "content": "待删除"})
        response = await self.client.delete(f"/api/v1/workspace/projects/{pid}")
        self.assertEqual(response.status_code, 200)
        self.created.remove(pid)
        from core.database import db_manager
        from models.messages import Messages
        from models.project_files import Project_files
        from sqlalchemy import func, select
        async with db_manager.session() as db:
            for model in (Messages, Project_files):
                count = (await db.execute(select(func.count()).select_from(model).where(model.project_id == pid))).scalar_one()
                self.assertEqual(count, 0)

    async def test_input_validation(self):
        pid = await self.new_project()
        for name in (" ", "字" * 41):
            response = await self.client.post("/api/v1/workspace/projects", json={"name": name})
            self.assertEqual(response.status_code, 422)
        response = await self.client.post(f"/api/v1/workspace/projects/{pid}/messages", json={"content": " ", "user_id": "forged"})
        self.assertEqual(response.status_code, 422)
        response = await self.client.put(f"/api/v1/workspace/projects/{pid}/files", json={"path": "../escape", "content": ""})
        self.assertEqual(response.status_code, 422)

    async def test_database_failure_is_explicit(self):
        self.as_user(self.uid)
        class BrokenSession:
            async def execute(self, *args, **kwargs):
                raise OperationalError("测试数据库故障", {}, RuntimeError("不可用"))
            async def rollback(self):
                pass
        async def broken_db():
            yield BrokenSession()
        self.app.dependency_overrides[workspace.workspace_db] = broken_db
        response = await self.client.get("/api/v1/workspace/projects")
        self.assertEqual(response.status_code, 503)
        self.assertIn("数据库暂时不可用", response.json()["detail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
