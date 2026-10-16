from fastapi import APIRouter

# 内部凭据仅供认证服务使用，禁止通用 CRUD。
router = APIRouter()
