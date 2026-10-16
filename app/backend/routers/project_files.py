from fastapi import APIRouter

# 私有业务数据仅通过 workspace 路由访问，禁止默认通用 CRUD 绕过关联授权。
router = APIRouter()
