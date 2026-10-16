import { useEffect, useRef, useState } from 'react';
import { Loader2, Monitor, ShieldCheck, TriangleAlert } from 'lucide-react';
import { errorMessage, workspaceApi, type PreviewCheck } from '@/lib/workspace-api';
import type { Project } from '@/lib/workspace';

export default function PreviewReadiness({ project }: { project: Project }) {
  const [report, setReport] = useState<PreviewCheck | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const pending = useRef(false);
  useEffect(() => {
    sequence.current += 1;
    pending.current = false;
    setReport(null); setError(''); setLoading(false);
    return () => { sequence.current += 1; };
  }, [project.id, project.files]);

  async function check() {
    if (pending.current) return;
    pending.current = true;
    const request = ++sequence.current;
    setLoading(true); setError(''); setReport(null);
    try {
      const result = await workspaceApi.checkPreview(project.id);
      if (request === sequence.current) setReport(result);
    } catch (issue) {
      if (request === sequence.current) setError(errorMessage(issue, '预检失败，请重试；没有启动构建。'));
    } finally {
      if (request === sequence.current) { pending.current = false; setLoading(false); }
    }
  }

  return <div className="preview-empty preview-readiness">
    <div className="preview-illustration"><Monitor size={38} strokeWidth={1.3} /></div>
    <span className="empty-pill">第四阶段 A · 只读预检</span>
    <h2>运行环境尚未配置</h2>
    <p>尚未确认可信的隔离运行服务。<br />只检查已保存文件，不安装依赖、不执行代码。</p>
    <button className="secondary-button" disabled={loading} onClick={check}>{loading ? <Loader2 size={15} className="spin" /> : <ShieldCheck size={15} />}{loading ? '正在读取数据库并预检…' : report ? '重新检测已保存文件' : '检测运行条件'}</button>
    <div className="preview-check-status" role="status">构建：未启动 · 运行：未启动 · 预览地址：无</div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {report && <div className="preview-check-report" aria-live="polite">
      <h3><TriangleAlert size={16} />运行已阻断</h3>
      <p>{report.reason}</p>
      <h3>静态预检：{report.preflight.status === 'issues_found' ? '发现问题' : '通过基础检查（非构建成功）'}</h3>
      <p>数据库文件：{report.source.file_count} 个 · 内容快照：{report.source.revision.slice(0, 12)}</p>
      {report.preflight.issues.length > 0 && <ul>{report.preflight.issues.map((item, index) => <li key={`${item.code}-${index}`}>{item.message}</li>)}</ul>}
      <p>{report.preflight.note}</p>
      <p>{report.logs_note}</p>
    </div>}
    <small>生成能力保留；文件修改后检测结果清空，需重新预检。没有创建运行任务或公开部署。</small>
  </div>;
}
