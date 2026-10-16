import { useSearchParams } from 'react-router-dom';
import { AlertCircle } from 'lucide-react';
import '@/workspace.css';

export default function AuthErrorPage() {
  const [params] = useSearchParams();
  return <main className="auth-screen"><section className="auth-card"><AlertCircle size={36} color="#b43b37" /><h1>认证未完成</h1><p role="alert">{params.get('msg') || '认证信息无效或已过期，请返回后重试。'}</p><a className="primary-button" href="/">返回登录入口</a></section></main>;
}
