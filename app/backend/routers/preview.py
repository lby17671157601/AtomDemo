"""授权后的数据库预检；运行接口默认拒绝，不创建运行资源。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_user
from models.project_files import Project_files
from routers.workspace import db_phase, owned_project, workspace_db
from schemas.auth import UserResponse
from services.preview_preflight import BLOCK_REASON, preflight
from services.workspace_generation import MAX_FILES

router = APIRouter(prefix="/api/v1/workspace", tags=["preview-preflight"])


@router.post("/projects/{project_id}/preview-check")
async def check_preview(project_id: int, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(workspace_db)):
    async with db_phase(db):
        await owned_project(db, project_id, current_user.id)
        rows = (await db.scalars(select(Project_files).where(Project_files.project_id == project_id, Project_files.user_id == str(current_user.id)).order_by(Project_files.path).limit(MAX_FILES + 1))).all()
        files = [{"path": row.path, "content": row.content} for row in rows]
        return preflight(files)


@router.post("/projects/{project_id}/preview")
async def start_preview(project_id: int, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(workspace_db)):
    async with db_phase(db):
        await owned_project(db, project_id, current_user.id)
        raise HTTPException(503, BLOCK_REASON)
