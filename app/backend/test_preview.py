"""真实数据库预检测试；没有模拟或执行构建器。"""
import json
import unittest
from unittest.mock import patch

import test_workspace
from routers import preview
from services.preview_preflight import preflight


def minimal_files(code="export default function App(){ return null; }"):
    return [
        {"path": "index.html", "content": '<div id="root"></div><script type="module" src="/src/main.tsx"></script>'},
        {"path": "src/main.tsx", "content": code},
        {"path": "package.json", "content": json.dumps({"dependencies": {"react": "18.3.1", "react-dom": "18.3.1"}, "devDependencies": {"vite": "5.4.21"}, "scripts": {"dev": "vite", "build": "vite build"}})},
    ]


class PreviewTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_workspace.WorkspaceIntegrationTests.asyncSetUp
    asyncTearDown = test_workspace.WorkspaceIntegrationTests.asyncTearDown
    as_user = test_workspace.WorkspaceIntegrationTests.as_user
    new_project = test_workspace.WorkspaceIntegrationTests.new_project

    async def check(self, pid):
        return await self.client.post(f"/api/v1/workspace/projects/{pid}/preview-check")

    async def setup_project(self):
        self.app.include_router(preview.router)
        return await self.new_project()

    async def test_empty_missing_entry_and_readback(self):
        pid = await self.setup_project()
        response = await self.check(pid)
        self.assertEqual(response.status_code, 200)
        self.assertIn("empty_project", [item["code"] for item in response.json()["preflight"]["issues"]])
        for file in minimal_files():
            self.assertEqual((await self.client.put(f"/api/v1/workspace/projects/{pid}/files", json=file)).status_code, 200)
        result = (await self.check(pid)).json()
        self.assertEqual(result["preflight"]["status"], "passed_static_checks")
        self.assertFalse(result["can_run"])
        self.assertIsNone(result["preview_url"])
        self.assertEqual(result["logs"], [])
        self.assertEqual(result["build_status"], "not_started")
        before = (await self.client.get(f"/api/v1/workspace/projects/{pid}/files")).json()
        await self.check(pid)
        after = (await self.client.get(f"/api/v1/workspace/projects/{pid}/files")).json()
        self.assertEqual(before, after)

    async def test_unauthorized_check_and_start(self):
        pid = await self.setup_project()
        self.app.dependency_overrides.clear()
        for suffix in ("preview-check", "preview"):
            self.assertEqual((await self.client.post(f"/api/v1/workspace/projects/{pid}/{suffix}")).status_code, 401)
        self.as_user("other-preview-user")
        for suffix in ("preview-check", "preview"):
            self.assertEqual((await self.client.post(f"/api/v1/workspace/projects/{pid}/{suffix}")).status_code, 404)
        self.as_user(self.uid)
        self.assertEqual((await self.client.post(f"/api/v1/workspace/projects/{pid}/preview")).status_code, 503)

    async def test_preflight_does_not_execute_or_forward_secrets(self):
        pid = await self.setup_project()
        for file in minimal_files("throw new Error('不可执行'); fetch('https://test.invalid')"):
            await self.client.put(f"/api/v1/workspace/projects/{pid}/files", json=file)
        with patch("subprocess.Popen", side_effect=AssertionError("禁止启动进程")), patch.dict("os.environ", {"APP_AI_KEY": "secret-sentinel", "DATABASE_URL": "db-secret-sentinel"}):
            response = await self.check(pid)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("secret-sentinel", response.text)
            self.assertEqual(response.json()["run_status"], "not_started")
        # 无效代码仍可能通过静态结构检查，不能将此结果称作构建成功。
        result = preflight(minimal_files("this is not valid JavaScript !!!"))
        self.assertEqual(result["preflight"]["status"], "passed_static_checks")
        self.assertFalse(result["can_run"])

    async def test_manifest_and_path_policy(self):
        for value in ("{}", "[]", "not json", json.dumps({"scripts": {"postinstall": "curl bad"}}), json.dumps({"dependencies": {"react": "https://bad"}})):
            files = minimal_files()
            files[-1]["content"] = value
            self.assertEqual(preflight(files)["preflight"]["status"], "issues_found")
        files = minimal_files()
        files[0]["content"] = '<script type="module" src="/src/missing.tsx"></script>'
        self.assertIn("missing_module", [item["code"] for item in preflight(files)["preflight"]["issues"]])
        files.append({"path": "../a.ts", "content": ""})
        self.assertIn("unsafe_path", [item["code"] for item in preflight(files)["preflight"]["issues"]])

    async def test_database_error_and_revision_change(self):
        pid = await self.setup_project()
        first = (await self.check(pid)).json()["source"]["revision"]
        await self.client.put(f"/api/v1/workspace/projects/{pid}/files", json={"path": "a.txt", "content": "修改"})
        second = (await self.check(pid)).json()["source"]["revision"]
        self.assertNotEqual(first, second)
        from sqlalchemy.exc import OperationalError
        class Broken:
            async def execute(self, *args):
                raise OperationalError("故障", {}, RuntimeError("测试"))
            async def rollback(self):
                pass
        async def broken_db():
            yield Broken()
        self.app.dependency_overrides[preview.workspace_db] = broken_db
        self.assertEqual((await self.check(pid)).status_code, 503)


if __name__ == "__main__":
    unittest.main(verbosity=2)
