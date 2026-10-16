import { client } from '@/lib/api';
import { demoOptions } from '@/lib/demo-auth';
import type { Project } from '@/lib/workspace';

export interface PreviewCheck {
  status: 'blocked'; can_run: false; preview_url: null; reason: string;
  build_status: 'not_started'; run_status: 'not_started';
  source: { file_count: number; revision: string; entry_paths: string[] };
  preflight: { status: 'issues_found' | 'passed_static_checks'; issues: { code: string; message: string }[]; note: string };
  logs: string[]; logs_note: string;
}
export interface ProjectRow { id: number; user_id: string; name: string; created_at: string; updated_at: string }
export interface MessageRow { id: number; user_id: string; project_id: number; role: 'user' | 'system' | 'assistant'; content: string; created_at: string }
export interface FileRow { id: number; user_id: string; project_id: number; path: string; content: string; updated_at: string }
export function errorMessage(issue: unknown, fallback = '操作失败，请重试。'): string {
  const error = issue as { response?: { data?: { detail?: unknown } }; data?: { detail?: unknown }; message?: string; code?: string };
  const detail = error?.response?.data?.detail || error?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return '输入格式不正确，请检查名称、内容或文件路径。';
  if (error?.code === 'ECONNABORTED' || error?.code === 'ETIMEDOUT') return '请求超时，保存结果尚未确认。请重新加载当前项目核对记录后再重试，输入已保留。';
  return error?.message || fallback;
}
async function invoke<T>(url: string, method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE', data = {}, timeout?: number): Promise<T> {
  try { const response = await client.apiCall.invoke({ url: `/api/v1/workspace${url}`, method, data, options: demoOptions(timeout) }); return response.data as T; }
  catch (issue) { throw new Error(errorMessage(issue, '数据库请求失败，未确认保存成功。')); }
}
async function all<T>(url: string): Promise<T[]> {
  const items: T[] = [];
  let total = 0;
  do {
    const page = await invoke<{ items: T[]; total: number }>(url, 'GET', { skip: items.length, limit: 100 });
    if (!Array.isArray(page?.items) || !Number.isInteger(page.total) || page.total < 0) {
      throw new Error('数据库返回的列表格式无效，未确认加载成功。');
    }
    items.push(...page.items); total = page.total;
    if (page.items.length === 0 && items.length < total) {
      throw new Error('项目数据分页未加载完整，请重试。');
    }
  } while (items.length < total);
  return items;
}
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
export const toMessages = (rows: MessageRow[]) => rows.map(row => ({ id: String(row.id), role: row.role, content: row.content, time: time(row.created_at) }));
export function toProject(row: ProjectRow): Project {
  return { id: String(row.id), name: row.name, messages: [], files: [], draft: '', history: [{ id: `created-${row.id}`, label: '创建项目（数据库记录）', time: time(row.created_at), kind: 'saved' }] };
}
export const workspaceApi = {
  list: () => all<ProjectRow>('/projects'),
  create: (name: string) => invoke<ProjectRow>('/projects', 'POST', { name }),
  rename: (id: string, name: string) => invoke<ProjectRow>(`/projects/${id}`, 'PATCH', { name }),
  remove: (id: string) => invoke<{ deleted: boolean }>(`/projects/${id}`, 'DELETE'),
  messages: (id: string) => all<MessageRow>(`/projects/${id}/messages`),
  files: (id: string) => all<FileRow>(`/projects/${id}/files`),
  send: (id: string, content: string) => invoke<{ items: MessageRow[] }>(`/projects/${id}/messages`, 'POST', { content }),
  generate: (id: string, content: string) => invoke<{ items: MessageRow[]; files: FileRow[]; summary: string }>(`/projects/${id}/generate`, 'POST', { content }, 600_000),
  checkPreview: async (id: string) => {
    const result = await invoke<PreviewCheck>(`/projects/${id}/preview-check`, 'POST', {}, 30_000);
    if (result?.status !== 'blocked' || result.can_run !== false || result.preview_url !== null || !Array.isArray(result.preflight?.issues)) {
      throw new Error('预检响应与安全契约不一致；不会打开或运行项目。');
    }
    return result;
  },
  saveFile: (id: string, path: string, content: string) => invoke<FileRow>(`/projects/${id}/files`, 'PUT', { path, content }),
};
export function withChildren(project: Project, messages: MessageRow[], files: FileRow[]): Project {
  const mapped = toMessages(messages);
  return { ...project, messages: mapped, files: files.map(file => ({ id: String(file.id), path: file.path, content: file.content })), history: [...project.history.slice(0, 1), ...mapped.filter(row => row.role !== 'system').map(row => ({ id: `message-${row.id}`, label: row.role === 'assistant' ? row.content : `需求：${row.content}`, time: row.time, kind: 'saved' as const }))] };
}
