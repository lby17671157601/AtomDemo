---
last_updated: 2026-10-16T14:59:14Z
---

# Architecture Design

## System Overview
Atoms Demo 第三阶段：React/Vite 工作台 + 原生托管认证 + Atoms Cloud 数据库 + 原生 gpt-5.4 服务端结构化生成。项目、消息与文件通过 /api/v1/workspace 保存；草稿仍为页面内存。AuthGate 用 SDK me 核验会话，toLogin 进入官方托管认证，回调沿用只读模板。生成代码不执行，构建沙箱和发布未配置。

## Tech Stack

## Module Design
| Module | Responsibility | Key Files |
|--------|---------------|-----------|
| 会话数据模型 | 项目、草稿、需求与历史契约，输入校验 | src/lib/workspace.ts |
| 页面状态编排 | 项目切换、本地发送、弹窗与状态 | src/pages/Index.tsx |
| 工作台面板 | 导航、对话、预览/代码/历史 | src/components/WorkspacePanels.tsx |
| 视觉系统 | 三栏布局与移动端导航 | src/workspace.css，DESIGN.md |

后端业务路由为 routers/workspace.py，生成服务为 services/workspace_generation.py；前端 SDK 数据层为 src/lib/workspace-api.ts，认证门禁为 src/components/AuthGate.tsx。生成采用短读事务→原生模型→重新授权与快照检查→同事务增量文件/消息保存；现有表契约不变。安全预览仍待后续阶段。

## Tech Decisions
| Decision | Choice | Rationale |
|----------|--------|-----------|
| 私有访问 | 每个 API 依赖原生 get_current_user，查询约束 user_id 并验证父项目 | 不依赖前端筛选 |
| 默认 CRUD | 清空三张业务表的生成路由，避免未授权 /all 和关联校验绕过 | 只保留业务 API；重新生成表后须重新关闭默认入口 |
| 删除策略 | 父项目行锁 + 单事务硬删除消息、文件与项目 | 禁止并发写入产生孤儿；没有数据库外键迁移 |
| 认证 | 仅原生 SDK 托管入口；注册能力待真实官方页面验证 | 不创建自定义密码系统 |

## File Tree Plan

## Implementation Guide

