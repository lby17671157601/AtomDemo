import { client } from '@/lib/api';

type AuthMode = 'demo' | 'original';
const MODE_KEY = 'atoms-demo-auth-mode';
let mode: AuthMode | null = null;
export function authMode(): AuthMode | null {
  if (mode) return mode;
  try {
    const saved = localStorage.getItem(MODE_KEY);
    return saved === 'demo' || saved === 'original' ? saved : null;
  } catch { return null; }
}
export function setAuthMode(value: AuthMode) {
  mode = value;
  try { localStorage.setItem(MODE_KEY, value); } catch { /* 非敏感标记；存储受限时仍支持当前会话。 */ }
}
export function demoOptions(timeout?: number) {
  return { withCredentials: true, ...(authMode() === 'demo' ? { headers: { 'X-Demo-Auth': '1' } } : {}), ...(timeout ? { timeout } : {}) };
}
export function authStatus(issue: unknown): number | undefined {
  const value = issue as { response?: { status?: number }; status?: number };
  return value?.response?.status || value?.status;
}
export function authError(issue: unknown): string {
  const messages: Record<number, string> = {
    401: '邮箱或密码不正确，或会话已失效，请重新登录。',
    403: '账号请求被拒绝，请从本站重新操作。',
    409: '这个邮箱已注册Demo账号，请使用邮箱登录。',
    413: '账号请求内容过大，请检查输入。',
    422: '请填写有效邮箱及10到128个字符的密码。',
    429: '尝试次数过多，请15分钟后再试。',
  };
  return messages[authStatus(issue) || 0] || '账号服务暂时不可用，尚未确认操作成功，请稍后重试。';
}
async function invoke(action: string, method: 'GET' | 'POST', data = {}) {
  const response = await client.apiCall.invoke({
    url: `/api/v1/demo-auth/${action}`, method, data,
    options: { withCredentials: true, headers: { 'X-Demo-Auth': '1' } },
  });
  return response.data as { authenticated?: boolean; logged_out?: boolean };
}
export const demoAuth = {
  me: async () => {
    const result = await invoke('me', 'GET');
    if (result.authenticated !== true) throw new Error('会话核验失败');
  },
  authenticate: async (action: 'login' | 'register', email: string, password: string) => {
    await invoke(action, 'POST', { email, password });
    // 即使网络中断也不自动回落到已存在的平台账号。
    setAuthMode('demo');
    await demoAuth.me();
  },
  logout: async () => {
    const result = await invoke('logout', 'POST');
    if (result.logged_out !== true) throw new Error('退出未确认');
    // 保留模式而非凭据，避免退出Demo后意外进入平台旧账号。
    setAuthMode('demo');
  },
};
