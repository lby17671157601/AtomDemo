"""模拟模型响应 + 真实数据库；不属于真实模型端到端验证。"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError
from sqlalchemy.exc import OperationalError

import test_workspace
from routers import workspace
from services import workspace_generation as generation


def payload(path="src/App.tsx", content="任务代码"):
    return json.dumps({"summary": "生成变更", "changes": [{"path": path, "content": content, "description": "更新功能"}]}, ensure_ascii=False)


class GenerationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_workspace.WorkspaceIntegrationTests.asyncSetUp
    asyncTearDown = test_workspace.WorkspaceIntegrationTests.asyncTearDown
    as_user = test_workspace.WorkspaceIntegrationTests.as_user
    new_project = test_workspace.WorkspaceIntegrationTests.new_project

    def model(self, outputs=None):
        return SimpleNamespace(client=SimpleNamespace(close=AsyncMock()), gentxt=AsyncMock(side_effect=[SimpleNamespace(content=text) for text in (outputs or [payload()])]))

    async def send(self, pid, content="创建任务管理应用"):
        return await self.client.post(f"/api/v1/workspace/projects/{pid}/generate", json={"content": content})

    async def children(self, pid, collection):
        return (await self.client.get(f"/api/v1/workspace/projects/{pid}/{collection}")).json()["items"]

    async def test_auth_and_ownership_before_model(self):
        pid = await self.new_project()
        self.app.dependency_overrides.clear()
        with patch.object(workspace, "generate_changes", new_callable=AsyncMock) as model:
            self.assertEqual((await self.send(pid)).status_code, 401)
            response = await self.client.post(f"/api/v1/workspace/projects/{pid}/generate", json={"content": "测试"}, headers={"Authorization": "Bearer invalid"})
            self.assertEqual(response.status_code, 401)
            self.as_user("other-generation-user")
            self.assertEqual((await self.send(pid)).status_code, 404)
            model.assert_not_awaited()
        self.as_user(self.uid)
        self.assertEqual(await self.children(pid, "files"), [])

    async def test_not_configured(self):
        pid = await self.new_project()
        with patch.object(generation, "AIHubService", return_value=SimpleNamespace(client=None)):
            response = await self.send(pid)
        self.assertEqual(response.status_code, 503)
        self.assertIn("尚未配置", response.json()["detail"])
        self.assertEqual(await self.children(pid, "messages"), [])

    async def test_three_rounds_context_incremental_and_readback(self):
        pid = await self.new_project()
        await self.client.put(f"/api/v1/workspace/projects/{pid}/files", json={"path": "src/style.css", "content": "保留样式"})
        model = self.model([payload(content="列表"), payload(content="列表+完成"), payload(content="列表+完成+筛选")])
        with patch.object(generation, "AIHubService", return_value=model):
            for requirement in ("创建任务", "增加完成", "增加筛选"):
                response = await self.send(pid, requirement)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["items"][1]["role"], "assistant")
                self.assertEqual(len(response.json()["files"]), 2)
        second = json.loads(model.gentxt.call_args_list[1].args[0].messages[1].content)
        third = json.loads(model.gentxt.call_args_list[2].args[0].messages[1].content)
        self.assertIn({"path": "src/App.tsx", "content": "列表"}, second["current_files"])
        self.assertIn({"path": "src/App.tsx", "content": "列表+完成"}, third["current_files"])
        self.assertEqual([row["content"] for row in third["recent_conversation"] if row["role"] == "user"], ["创建任务", "增加完成"])
        files = {row["path"]: row["content"] for row in await self.children(pid, "files")}
        self.assertEqual(files, {"src/style.css": "保留样式", "src/App.tsx": "列表+完成+筛选"})
        messages = await self.children(pid, "messages")
        self.assertEqual(len(messages), 6)
        self.assertIn("src/App.tsx：更新功能", messages[-1]["content"])

    async def test_paths_and_invalid_model_output(self):
        pid = await self.new_project()
        for path in ("../escape.ts", "/a.ts", "src\\a.ts", "src//a.js", ".env", ".atoms/a.json", "backend/main.py", "src/core/a.ts", "a.sh", "a\x00.ts", "C:/a.ts", "src/%2e%2e/a.ts"):
            self.assertEqual((await self.client.put(f"/api/v1/workspace/projects/{pid}/files", json={"path": path, "content": ""})).status_code, 422, path)
            with self.assertRaises(ValueError):
                generation.parse_result(payload(path=path))
        model = self.model([payload(path="../a.ts"), payload(path=".env")])
        with patch.object(generation, "AIHubService", return_value=model):
            self.assertEqual((await self.send(pid)).status_code, 502)
        self.assertEqual(model.gentxt.await_count, 2)
        self.assertEqual(await self.children(pid, "files"), [])
        self.assertEqual(await self.children(pid, "messages"), [])

    async def test_repair_and_schema_limits(self):
        pid = await self.new_project()
        model = self.model(['{"summary":"缺字段"}', "```json\n" + payload() + "\n```"])
        with patch.object(generation, "AIHubService", return_value=model):
            response = await self.send(pid)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(model.gentxt.await_count, 2)
        for data in ({"summary": "无修改", "changes": []}, {"summary": "重复", "changes": [{"path": "a.ts", "content": "", "description": "更新"}] * 2}, {"summary": "过长", "changes": [{"path": "a.ts", "content": "x" * 100001, "description": "更新"}]}):
            with self.assertRaises(ValueError):
                generation.parse_result(json.dumps(data))

    async def test_internal_timeout_mapping(self):
        import asyncio
        pid = await self.new_project()
        model = self.model()
        async def slow(*args):
            await asyncio.sleep(1)
        model.gentxt.side_effect = slow
        with patch.object(generation, "AIHubService", return_value=model), patch.object(generation, "CALL_TIMEOUT", 0.001):
            self.assertEqual((await self.send(pid)).status_code, 504)
        self.assertEqual(await self.children(pid, "messages"), [])

    async def test_model_errors_do_not_save(self):
        pid = await self.new_project()
        request = httpx.Request("POST", "https://test.invalid")
        errors = [(APITimeoutError(request=request), 504), (APIConnectionError(request=request), 503), (RuntimeError("失败"), 502)]
        for code, expected in ((429, 429), (401, 503), (500, 503), (400, 502)):
            errors.append((APIStatusError("测试", response=httpx.Response(code, request=request), body=None), expected))
        for error, expected in errors:
            model = self.model()
            model.gentxt.side_effect = error
            with patch.object(generation, "AIHubService", return_value=model):
                self.assertEqual((await self.send(pid)).status_code, expected)
        self.assertEqual(await self.children(pid, "files"), [])
        self.assertEqual(await self.children(pid, "messages"), [])

    async def test_database_write_failure_rolls_back(self):
        pid = await self.new_project()
        result = generation.GenerationResult.model_validate({"summary": "多文件", "changes": [{"path": path, "content": "内容", "description": "更新"} for path in ("src/a.ts", "src/b.ts")]})
        real_upsert = workspace.upsert_file
        calls = 0
        async def broken_write(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                await args[0].flush()
                raise OperationalError("写入故障", {}, RuntimeError("测试"))
            return await real_upsert(*args)
        with patch.object(workspace, "generate_changes", AsyncMock(return_value=result)), patch.object(workspace, "upsert_file", broken_write):
            self.assertEqual((await self.send(pid)).status_code, 503)
        self.assertEqual(await self.children(pid, "files"), [])
        self.assertEqual(await self.children(pid, "messages"), [])

    async def test_no_transaction_during_model_and_conflict(self):
        pid = await self.new_project()
        await self.client.put(f"/api/v1/workspace/projects/{pid}/files", json={"path": "src/App.tsx", "content": "原内容"})
        from core.database import get_db
        sessions = []
        async def capture_db():
            async for db in get_db():
                sessions.append(db)
                yield db
        self.app.dependency_overrides[workspace.workspace_db] = capture_db
        async def concurrent_change(*args):
            self.assertFalse(sessions[0].in_transaction())
            await self.client.put(f"/api/v1/workspace/projects/{pid}/files", json={"path": "src/App.tsx", "content": "并发修改"})
            return generation.parse_result(payload(content="不应保存"))
        with patch.object(workspace, "generate_changes", concurrent_change):
            self.assertEqual((await self.send(pid)).status_code, 409)
        self.assertEqual((await self.children(pid, "files"))[0]["content"], "并发修改")
        self.assertEqual(await self.children(pid, "messages"), [])

    async def test_project_deleted_during_call(self):
        pid = await self.new_project()
        async def remove_during_call(*args):
            await self.client.delete(f"/api/v1/workspace/projects/{pid}")
            self.created.remove(pid)
            return generation.parse_result(payload())
        with patch.object(workspace, "generate_changes", remove_during_call):
            self.assertEqual((await self.send(pid)).status_code, 404)

    async def test_context_limit_before_model(self):
        pid = await self.new_project()
        await self.client.put(f"/api/v1/workspace/projects/{pid}/files", json={"path": "src/data.txt", "content": "x" * 200001})
        with patch.object(workspace, "generate_changes", new_callable=AsyncMock) as model:
            self.assertEqual((await self.send(pid)).status_code, 413)
            model.assert_not_awaited()


if __name__ == "__main__":
    unittest.main(verbosity=2)
