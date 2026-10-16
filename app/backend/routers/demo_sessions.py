from fastapi import APIRouter

# 内部会话仅供认证服务使用，禁止通用 CRUD。
router = APIRouter()
