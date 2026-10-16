"""手动执行的真实原生模型+数据库验证；测试身份不代表官方登录验收。"""
import unittest
import test_generation


class NativeGenerationSmoke(test_generation.GenerationTests):
    async def test_native_three_rounds(self):
        pid = await self.new_project()
        for requirement in ("创建简单的任务管理应用，React 支持输入并新增任务，不使用外部服务。", "基于已有文件为任务增加完成状态，保留新增任务功能。", "基于已有文件增加全部、未完成、已完成任务筛选，保留新增和完成状态。"):
            response = await self.send(pid, requirement)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertGreater(len(result["files"]), 0)
            self.assertEqual(result["items"][1]["role"], "assistant")
            stored = await self.children(pid, "files")
            self.assertEqual({row["path"]: row["content"] for row in stored}, {row["path"]: row["content"] for row in result["files"]})
            print(f"原生模型轮次完成：文件数={len(stored)}；数据库读回一致", flush=True)
        self.assertEqual(len(await self.children(pid, "messages")), 6)
        print("真实模型三轮接口与数据库保存通过；未运行生成代码，未验证官方登录。", flush=True)


if __name__ == "__main__":
    unittest.main(defaultTest="NativeGenerationSmoke.test_native_three_rounds", verbosity=2)
