export interface Message {
  id: string;
  role: 'user' | 'system' | 'assistant';
  content: string;
  time: string;
}
export interface Project {
  id: string;
  name: string;
  messages: Message[];
  files: { id: string; path: string; content: string }[];
  history: { id: string; label: string; time: string; kind: 'saved' | 'error' }[];
  draft: string;
}
export type WorkspaceView = 'Preview' | 'Code' | 'History';
export const services = [
  { name: 'AI 代码生成', configured: true, description: '已接入原生模型的受控服务端接口；实际可用性以请求结果为准。模型响应校验后保存到数据库，失败不清空输入；不执行代码。' },
  { name: '数据库与认证', configured: true, description: '已接入原生认证和私有数据库 API；具体操作以服务器返回结果为准。未发送的输入草稿仍仅保留在页面内存。' },
  { name: '安全运行环境', configured: false, description: '只读运行预检已接入；尚无经过验证的隔离服务，不安装依赖、不运行代码，不创建预览地址。' },
  { name: '项目发布', configured: false, description: '尚未接入项目部署服务；此入口仅展示配置状态。' },
];
export function validateName(value: string): string {
  const name = value.trim();
  if (!name) throw new Error('请输入项目名称。');
  if (name.length > 40) throw new Error('项目名称不能超过 40 个字符。');
  return name;
}
export function validateRequest(value: string): string {
  const content = value.trim();
  if (!content) throw new Error('请先输入你的需求。');
  if (content.length > 4000) throw new Error('单次需求不能超过 4000 个字符。');
  return content;
}
