"""认证路由脱敏回归；模拟 OIDC，不代表真实账号认证。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from routers import auth


class AuthPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_redirect_is_not_logged(self):
        user = SimpleNamespace(id="synthetic-user")
        service = SimpleNamespace(
            get_and_delete_oidc_state=AsyncMock(return_value={"nonce": "synthetic-nonce"}),
            get_or_create_user=AsyncMock(return_value=user),
            issue_app_token=AsyncMock(return_value=("synthetic-secret-marker", SimpleNamespace(timestamp=lambda: 1), {})),
        )
        response = SimpleNamespace(status_code=200, json=lambda: {"id_token": "synthetic-id-marker"})
        http = AsyncMock()
        http.post.return_value = response
        request = SimpleNamespace(headers={"host": "example.invalid"})
        with patch("services.auth.AuthService", return_value=service), patch("httpx.AsyncClient") as client, patch.object(
            auth, "validate_id_token", AsyncMock(return_value={"nonce": "synthetic-nonce", "sub": "synthetic-user"})
        ), self.assertLogs(auth.logger, level="INFO") as logs:
            client.return_value.__aenter__.return_value = http
            result = await auth.callback(request, code="synthetic-code", state="synthetic-state", db=None)
        self.assertEqual(result.status_code, 302)
        self.assertIn("synthetic-secret-marker", result.headers["location"])
        self.assertNotIn("synthetic-secret-marker", "\n".join(logs.output))
        self.assertNotIn("synthetic-id-marker", "\n".join(logs.output))

    async def test_token_exchange_failure_hides_raw_body(self):
        service = SimpleNamespace(get_and_delete_oidc_state=AsyncMock(return_value={"nonce": "synthetic-nonce"}))
        http = AsyncMock()
        http.post.return_value = SimpleNamespace(status_code=400, text="synthetic-sensitive-body")
        request = SimpleNamespace(headers={"host": "example.invalid"})
        with patch("services.auth.AuthService", return_value=service), patch("httpx.AsyncClient") as client, self.assertLogs(
            auth.logger, level="ERROR"
        ) as logs:
            client.return_value.__aenter__.return_value = http
            result = await auth.callback(request, code="synthetic-code", state="synthetic-state", db=None)
        self.assertEqual(result.status_code, 302)
        self.assertNotIn("synthetic-sensitive-body", result.headers["location"])
        self.assertNotIn("synthetic-sensitive-body", "\n".join(logs.output))

    async def test_platform_verification_failure_hides_message(self):
        http = AsyncMock()
        http.post.return_value = SimpleNamespace(
            status_code=401, json=lambda: {"success": False, "message": "synthetic-sensitive-body"}
        )
        with patch("httpx.AsyncClient") as client, self.assertLogs(auth.logger, level="WARNING") as logs:
            client.return_value.__aenter__.return_value = http
            with self.assertRaises(auth.HTTPException) as failure:
                await auth.exchange_platform_token(auth.PlatformTokenExchangeRequest(platform_token="synthetic-token"), db=None)
        self.assertEqual(failure.exception.status_code, 401)
        self.assertNotIn("synthetic-sensitive-body", failure.exception.detail)
        self.assertNotIn("synthetic-sensitive-body", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
