import hashlib
import json
import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from models.projects import Projects
from models.messages import Messages
from models.project_files import Project_files
from schemas.auth import UserResponse
from services.workspace_generation import MAX_CONTEXT_CHARS, MAX_FILES, generate_changes, validate_file_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/workspace", tags=["workspace"])
AI_NOTICE = "需求已保存（仅消息存储）。本操作没有调用模型或修改代码；请通过工作台的生成入口请求 AI。"


async def workspace_db():
    try:
        async for session in get_db():
            yield session
    except (SQLAlchemyError, ValueError, OSError, AttributeError):
        logger.exception("数据库连接或操作失败")
        raise HTTPException(503, "数据库暂时不可用，操作未确认成功，请稍后重试。")


class NameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        if not value.strip():
            raise ValueError("项目名称不能为空")
        return value.strip()


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def trim_content(cls, value):
        if not value.strip():
            raise ValueError("需求不能为空")
        return value.strip()


class FileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=1000000)

    @field_validator("path")
    @classmethod
    def safe_path(cls, value):
        return validate_file_path(value)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: str
    name: str
    created_at: object
    updated_at: object


@asynccontextmanager
async def db_phase(db):
    try:
        yield
    except SQLAlchemyError:
        try:
            await db.rollback()
        except SQLAlchemyError:
            pass
        logger.exception("工作台数据库操作失败")
        raise HTTPException(503, "数据库暂时不可用，操作未确认成功，请稍后重试。")


async def owned_project(db, project_id, user_id, lock=False):
    statement = select(Projects).execution_options(populate_existing=True).where(Projects.id == project_id, Projects.user_id == str(user_id))
    if lock:
        statement = statement.with_for_update()
    item = (await db.execute(statement)).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "项目不存在或无权访问。")
    return item


def serialize(item):
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


@router.get("/projects")
async def list_projects(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(workspace_db)):
    async with db_phase(db):
        scope = Projects.user_id == str(current_user.id)
        total = (await db.execute(select(func.count()).select_from(Projects).where(scope))).scalar_one()
        rows = (await db.scalars(select(Projects).where(scope).order_by(Projects.id.desc()).offset(skip).limit(limit))).all()
        return {"items": [serialize(row) for row in rows], "total": total}


@router.post("/projects", status_code=201)
async def create_project(data: NameInput, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(workspace_db)):
    async with db_phase(db):
        row = Projects(user_id=str(current_user.id), name=data.name)
        db.add(row)
        await db.commit()
        return serialize(row)


@router.patch("/projects/{project_id}")
async def rename_project(project_id: int, data: NameInput, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(workspace_db)):
    async with db_phase(db):
        row = await owned_project(db, project_id, current_user.id, lock=True)
        row.name = data.name
        await db.commit()
        return serialize(row)


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(workspace_db)):
    async with db_phase(db):
        row = await owned_project(db, project_id, current_user.id, lock=True)
        # 删除父项目和其全部关联数据在一个事务内完成；所有写入都先锁定父项目。
        await db.execute(delete(Messages).where(Messages.project_id == project_id))
        await db.execute(delete(Project_files).where(Project_files.project_id == project_id))
        await db.delete(row)
        await db.commit()
        return {"deleted": True, "id": project_id}


@router.get("/projects/{project_id}/{collection}")
async def list_children(project_id: int, collection: Literal["messages", "files"], skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200), current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(workspace_db)):
    async with db_phase(db):
        await owned_project(db, project_id, current_user.id)
        model = Messages if collection == "messages" else Project_files
        scope = (model.project_id == project_id, model.user_id == str(current_user.id))
        rows = (await db.scalars(select(model).where(*scope).order_by(model.id).offset(skip).limit(limit))).all()
        total = (await db.execute(select(func.count()).select_from(model).where(*scope))).scalar_one()
        return {"items": [serialize(row) for row in rows], "total": total}


@router.post("/projects/{project_id}/messages", status_code=201)
async def add_message(project_id: int, data: MessageInput, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(workspace_db)):
    async with db_phase(db):
        await owned_project(db, project_id, current_user.id, lock=True)
        rows = [Messages(project_id=project_id, user_id=str(current_user.id), role="user", content=data.content), Messages(project_id=project_id, user_id=str(current_user.id), role="system", content=AI_NOTICE)]
        db.add_all(rows)
        await db.commit()
        return {"items": [serialize(row) for row in rows]}


async def upsert_file(db, project_id, user_id, path, content):
    row = (await db.execute(select(Project_files).where(Project_files.project_id == project_id, Project_files.user_id == str(user_id), Project_files.path == path))).scalar_one_or_none()
    if row is None:
        row = Project_files(project_id=project_id, user_id=str(user_id), path=path, content=content)
        db.add(row)
    else:
        row.content = content
    return row


async def generation_snapshot(db, project_id, user_id):
    scope = (Project_files.project_id == project_id, Project_files.user_id == str(user_id))
    rows = (await db.scalars(select(Project_files).execution_options(populate_existing=True).where(*scope).order_by(Project_files.id).limit(MAX_FILES + 1))).all()
    history = (await db.scalars(select(Messages).where(Messages.project_id == project_id, Messages.user_id == str(user_id)).order_by(Messages.id.desc()).limit(20))).all()
    files = [{"path": row.path, "content": row.content} for row in rows]
    conversation = [{"role": row.role, "content": row.content} for row in reversed(history) if row.role in ("user", "assistant")]
    if len(rows) > MAX_FILES or len(json.dumps([files, conversation], ensure_ascii=False)) > MAX_CONTEXT_CHARS:
        raise HTTPException(413, "项目上下文超过本阶段限制（80个文件、200000字符），未调用模型；请缩小项目后重试。")
    token = hashlib.sha256(json.dumps({"files": [(row.id, row.path, row.content, str(row.updated_at)) for row in rows], "messages": [(row.id, row.role, row.content) for row in history]}, ensure_ascii=False).encode()).hexdigest()
    return files, conversation, token


@router.post("/projects/{project_id}/generate")
async def generate_project(project_id: int, data: MessageInput, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(workspace_db)):
    uid = str(current_user.id)
    async with db_phase(db):
        project = await owned_project(db, project_id, uid)
        name = project.name
        files, history, token = await generation_snapshot(db, project_id, uid)
        await db.commit()
    result = await generate_changes(data.content, name, files, history)
    async with db_phase(db):
        project = await owned_project(db, project_id, uid, lock=True)
        current_files, _, current_token = await generation_snapshot(db, project_id, uid)
        if token != current_token or project.name != name:
            raise HTTPException(409, "生成期间项目已被修改；本轮未保存，请重新加载项目后重试。")
        existing_paths = {item["path"].lower(): item["path"] for item in current_files}
        for change in result.changes:
            validate_file_path(change.path)
            if change.path.lower() in existing_paths and existing_paths[change.path.lower()] != change.path:
                raise HTTPException(502, "模型路径与已有文件大小写冲突，未保存修改。")
        projected = {item["path"]: item["content"] for item in current_files}
        projected.update({change.path: change.content for change in result.changes})
        if len(projected) > MAX_FILES or len(json.dumps([projected, history], ensure_ascii=False)) + len(data.content) + len(result.message()) > MAX_CONTEXT_CHARS:
            raise HTTPException(413, "生成后项目将超过上下文限制，未保存修改，请缩小需求。")
        for change in result.changes:
            await upsert_file(db, project_id, uid, change.path, change.content)
        messages = [Messages(project_id=project_id, user_id=uid, role="user", content=data.content), Messages(project_id=project_id, user_id=uid, role="assistant", content=result.message())]
        db.add_all(messages)
        await db.flush()
        stored = (await db.scalars(select(Project_files).where(Project_files.project_id == project_id, Project_files.user_id == uid).order_by(Project_files.id))).all()
        response = {"items": [serialize(row) for row in messages], "files": [serialize(row) for row in stored], "summary": result.summary, "model": "gpt-5.4"}
        await db.commit()
        return response


@router.put("/projects/{project_id}/files")
async def save_file(project_id: int, data: FileInput, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(workspace_db)):
    async with db_phase(db):
        await owned_project(db, project_id, current_user.id, lock=True)
        row = await upsert_file(db, project_id, current_user.id, data.path, data.content)
        await db.commit()
        return serialize(row)
