import { useEffect, useRef, useState } from 'react';
import { Box, Loader2, LogIn, ShieldCheck } from 'lucide-react';
import { client } from '@/lib/api';
import { authError, authMode, authStatus, demoAuth, setAuthMode } from '@/lib/demo-auth';
import '@/workspace.css';
import '@/phase-two.css';

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<'loading' | 'authenticated' | 'anonymous' | 'unavailable'>('loading');
  const [action, setAction] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);

  useEffect(() => {
    let alive = true;
    async function restore() {
      try {
        const selected = authMode();
        if (selected !== 'original') {
          try {
            await demoAuth.me();
            setAuthMode('demo');
            if (alive) setState('authenticated');
            return;
          } catch (issue) {
            if (authStatus(issue) !== 401) throw issue;
            if (selected === 'demo') {
              if (alive) setState('anonymous');
              return;
            }
          }
        }
        const response = await client.auth.me();
        if (response?.data) setAuthMode('original');
        if (alive) setState(response?.data ? 'authenticated' : 'anonymous');
      } catch (issue) {
        if (!alive) return;
        if (authStatus(issue) === 401) setState('anonymous');
        else {
          setError('暂时无法核验会话，可重试核验或使用下方邮箱登录。');
          setState('unavailable');
        }
      }
    }
    void restore();
    return () => { alive = false; };
  }, []);

  async function officialLogin() {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setError('');
    try {
      setAuthMode('original');
      await client.auth.toLogin();
    } catch {
      setError('无法打开原登录入口，请稍后重试。');
      submitting.current = false; setBusy(false);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current) return;
    if (action === 'register' && password !== confirmation) {
      setError('两次输入的密码不一致。');
      return;
    }
    submitting.current = true; setBusy(true); setError('');
    try {
      await demoAuth.authenticate(action, email.trim(), password);
      setPassword(''); setConfirmation('');
      setState('authenticated');
    } catch (issue) {
      setError(authError(issue));
      setPassword(''); setConfirmation('');
    } finally { submitting.current = false; setBusy(false); }
  }

  if (state === 'authenticated') return <>{children}</>;
  return <main className="auth-screen">
    <section className="auth-card" aria-labelledby="auth-title">
      <div className="brand-mark"><Box size={25} /></div>
      <span className="eyebrow">ATOMS DEMO · 私有工作空间</span>
      <h1 id="auth-title">{state === 'loading' ? '正在恢复登录状态' : action === 'register' ? '创建你的Demo账号' : '登录你的开发工作空间'}</h1>
      <p>项目与对话保存到数据库，每个账号仅访问自己的项目。</p>
      {state === 'loading' ? <Loader2 className="spin" size={24} aria-label="正在核验会话" /> : <>
        <div className="auth-tabs" role="group" aria-label="邮箱账号操作">
          {(['login', 'register'] as const).map(value => <button key={value} type="button" aria-pressed={action === value} disabled={busy} onClick={() => { setAction(value); setError(''); setPassword(''); setConfirmation(''); }}>{value === 'login' ? '邮箱登录' : '创建账号'}</button>)}
        </div>
        <form className="auth-form" onSubmit={submit}>
          <label htmlFor="demo-email">邮箱</label>
          <input id="demo-email" name="email" type="email" autoComplete="username" maxLength={254} value={email} required disabled={busy} onChange={event => setEmail(event.target.value)} />
          <label htmlFor="demo-password">密码</label>
          <input id="demo-password" name="password" type="password" autoComplete={action === 'register' ? 'new-password' : 'current-password'} minLength={10} maxLength={128} value={password} required disabled={busy} aria-describedby="password-help" onChange={event => setPassword(event.target.value)} />
          <small id="password-help">10–128个字符，请勿重复使用其他服务的密码。</small>
          {action === 'register' && <><label htmlFor="demo-confirmation">确认密码</label><input id="demo-confirmation" name="confirmation" type="password" autoComplete="new-password" minLength={10} maxLength={128} value={confirmation} required disabled={busy} onChange={event => setConfirmation(event.target.value)} /></>}
          {error && <p className="form-error auth-error" role="alert">{error}</p>}
          <button type="submit" className="primary-button" disabled={busy}>{busy ? <Loader2 className="spin" size={16} /> : <LogIn size={16} />}{busy ? '正在核验账号…' : action === 'register' ? '创建账号并登录' : '登录工作空间'}</button>
        </form>
        <p className="auth-detail">这是本Demo的独立账号，不会接管原账号或 test01。邮箱尚不验证，本Demo不发送验证邮件，也不提供密码找回。</p>
        <div className="auth-original"><span>已有原账号？</span><button className="secondary-button" disabled={busy} onClick={officialLogin}>使用原登录入口</button></div>
        <button className="auth-recheck" disabled={busy} onClick={() => window.location.reload()}>重新核验会话</button>
      </>}
      <div className="auth-footnote"><ShieldCheck size={15} />账号隔离 · 数据库持久化</div>
    </section>
  </main>;
}
