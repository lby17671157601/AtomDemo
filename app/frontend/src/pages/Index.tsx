import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, ChevronRight, Circle, Loader2, LogOut, Menu, Pencil, Plus, Rocket, Trash2, TriangleAlert, X } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ConversationPanel, PreviewPanel, ProjectSidebar } from '@/components/WorkspacePanels';
import { services, validateName, validateRequest, type Project, type WorkspaceView } from '@/lib/workspace';
import { errorMessage, toMessages, toProject, withChildren, workspaceApi } from '@/lib/workspace-api';
import { useQueryClient } from '@tanstack/react-query';
import { authMode, demoAuth } from '@/lib/demo-auth';
import { client } from '@/lib/api';
import '@/workspace.css';

export default function WorkspacePage() {
  const queryClient = useQueryClient();
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeId, setActiveId] = useState('');
  const [view, setView] = useState<WorkspaceView>('Preview');
  const [filesOpen, setFilesOpen] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [modal, setModal] = useState<'create' | 'rename' | 'delete' | 'info' | 'publish' | null>(null);
  const [projectName, setProjectName] = useState('');
  const [nameError, setNameError] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [listLoading, setListLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const inFlight = useRef(false);
  const project = projects.find(item => item.id === activeId);

  async function refreshProjects() {
    setListLoading(true); setError('');
    try {
      const rows = await workspaceApi.list();
      setProjects(rows.map(toProject));
      setRetry(value => value + 1);
      setActiveId(previous => rows.some(row => String(row.id) === previous) ? previous : rows.length ? String(rows[0].id) : '');
    } catch (issue) { setError(errorMessage(issue)); }
    finally { setListLoading(false); }
  }
  useEffect(() => { void refreshProjects(); }, []);
  useEffect(() => {
    if (!activeId) return;
    let alive = true;
    setDetailLoading(true); setDetailError('');
    Promise.all([workspaceApi.messages(activeId), workspaceApi.files(activeId)]).then(([messages, files]) => {
      if (alive) setProjects(current => current.map(item => item.id === activeId ? withChildren(item, messages, files) : item));
    }).catch(issue => { if (alive) setDetailError(errorMessage(issue)); }).finally(() => { if (alive) setDetailLoading(false); });
    return () => { alive = false; };
  }, [activeId, retry]);

  function selectProject(id: string) {
    if (inFlight.current) return;
    setActiveId(id); setError(''); setNotice(''); setMobileNav(false);
  }
  function openEdit(kind: 'create' | 'rename') {
    if (inFlight.current) return;
    setProjectName(kind === 'rename' ? project?.name || '' : ''); setNameError(''); setModal(kind);
  }
  async function editProject(event: React.FormEvent) {
    event.preventDefault();
    if (inFlight.current) return;
    try {
      const name = validateName(projectName);
      inFlight.current = true; setBusy(true); setNameError('');
      if (modal === 'create') {
        const saved = toProject(await workspaceApi.create(name));
        setProjects(current => [saved, ...current]); setActiveId(saved.id);
        setNotice('项目已保存到数据库。');
      } else if (project) {
        const saved = await workspaceApi.rename(project.id, name);
        setProjects(current => current.map(item => item.id === project.id ? { ...item, name: saved.name } : item));
        setNotice('项目名称已保存。');
      }
      setModal(null); setMobileNav(false);
    } catch (issue) { setNameError(errorMessage(issue)); }
    finally { inFlight.current = false; setBusy(false); }
  }
  async function removeProject() {
    if (!project || inFlight.current) return;
    inFlight.current = true; setBusy(true); setNameError('');
    try {
      await workspaceApi.remove(project.id);
      const remaining = projects.filter(item => item.id !== project.id);
      setProjects(remaining); setActiveId(remaining[0]?.id || ''); setModal(null);
      setNotice('项目及关联消息、文件已从数据库删除。');
    } catch (issue) { setNameError(errorMessage(issue)); }
    finally { inFlight.current = false; setBusy(false); }
  }
  async function sendRequest() {
    if (!project || detailLoading || detailError || inFlight.current) return;
    try {
      const content = validateRequest(project.draft);
      inFlight.current = true; setBusy(true); setError(''); setNotice('');
      const result = await workspaceApi.generate(project.id, content);
      const messages = toMessages(result.items);
      setProjects(current => current.map(item => item.id === project.id ? {
        ...item, draft: '', messages: [...item.messages, ...messages],
        files: result.files.map(file => ({ id: String(file.id), path: file.path, content: file.content })),
        history: [...item.history, ...messages.map(row => ({ id: `message-${row.id}`, label: row.role === 'assistant' ? row.content : `需求：${row.content}`, time: row.time, kind: 'saved' as const }))],
      } : item));
      setView('Code');
      setNotice('模型返回的文件已通过校验并保存到数据库；未执行代码。');
    } catch (issue) { setError(errorMessage(issue)); }
    finally { inFlight.current = false; setBusy(false); }
  }
  async function logout() {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError('');
    try {
      const independent = authMode() === 'demo';
      if (independent) await demoAuth.logout();
      else await client.auth.logout();
      setProjects([]); setActiveId(''); setModal(null); setNotice('');
      queryClient.clear();
      if (independent) window.location.assign('/');
    }
    catch (issue) { setError(errorMessage(issue, '登出失败，请重试。')); inFlight.current = false; setBusy(false); }
  }
  return <div className="workbench">
    {mobileNav && <button className="nav-scrim" aria-label="关闭项目导航" onClick={() => setMobileNav(false)} />}
    <aside className={`sidebar ${mobileNav ? 'mobile-open' : ''}`} aria-label="工作空间导航"><button className="mobile-close icon-button" aria-label="关闭导航" onClick={() => setMobileNav(false)}><X size={18} /></button><ProjectSidebar projects={projects} activeId={activeId} filesOpen={filesOpen} onSelect={selectProject} onCreate={() => openEdit('create')} onFiles={() => { setFilesOpen(current => !current); setView('Code'); }} onInfo={() => setModal('info')} /></aside>
    <main className="workspace-main"><header className="topbar"><div className="project-breadcrumb"><button className="menu-toggle icon-button" aria-label="打开项目导航" aria-expanded={mobileNav} onClick={() => setMobileNav(true)}><Menu size={20} /></button><span className="breadcrumb-parent">工作空间</span><ChevronRight className="breadcrumb-parent" size={14} /><span className="project-heading">{project?.name || '我的项目'}</span><span className="draft-tag">数据库</span></div><div className="topbar-actions">{project && <><button className="icon-button" disabled={busy} aria-label="重命名当前项目" title="重命名项目" onClick={() => openEdit('rename')}><Pencil size={15} /></button><button className="icon-button" disabled={busy} aria-label="删除当前项目" title="删除项目" onClick={() => { setNameError(''); setModal('delete'); }}><Trash2 size={15} /></button></>}<span className="runtime-badge"><Circle size={7} fill="currentColor" />未配置运行环境</span><button className="publish-button" onClick={() => setModal('publish')}><Rocket size={15} /><span>发布</span></button><button className="icon-button" disabled={busy} aria-label="登出" title="登出" onClick={logout}><LogOut size={17} /></button></div></header>
      <div className="phase-banner"><span><span className="phase-dot" />第四阶段 A<span className="banner-divider">/</span>安全预览条件检查</span><button onClick={() => setModal('info')}>模型接口 / 安全边界<ChevronRight size={14} /></button></div>
      {notice && <div className="success-notice" role="status"><CheckCircle2 size={16} />{notice}<button className="icon-button" aria-label="关闭提示" onClick={() => setNotice('')}><X size={14} /></button></div>}
      {error && <div className="database-error" role="alert"><TriangleAlert size={16} /><span>{error} 输入不会因失败清空；可再次发送重试。</span><button onClick={() => setRetry(value => value + 1)} disabled={busy || listLoading}>重新加载当前项目</button></div>}
      {listLoading ? <div className="workspace-empty" role="status"><Loader2 className="spin" />正在从数据库加载项目…</div> : !project ? <div className="workspace-empty"><h1>{error ? '项目加载失败' : '开始你的第一个项目'}</h1><p>{error ? '项目列表加载失败，请重试后再继续。' : '项目将保存到你的私有工作空间。'}</p>{error ? <button className="secondary-button" disabled={listLoading} onClick={refreshProjects}>重试加载项目列表</button> : <button className="primary-button" disabled={busy} onClick={() => openEdit('create')}><Plus size={16} />创建项目</button>}</div> : <div className="workspace-panels">{detailLoading || detailError ? <section className="chat-panel"><div className="workspace-empty">{detailLoading ? <><Loader2 className="spin" />正在加载消息和文件…</> : <><p role="alert" className="form-error">{detailError}</p><button className="secondary-button" onClick={() => setRetry(value => value + 1)}>重试加载</button></>}</div></section> : <ConversationPanel project={project} busy={busy} error="" onDraft={draft => { setProjects(current => current.map(item => item.id === activeId ? { ...item, draft } : item)); setError(''); }} onSend={sendRequest} onInfo={() => setModal('info')} />}<PreviewPanel key={project.id} project={detailLoading || detailError ? { ...project, files: [], messages: [], history: [] } : project} view={view} onView={setView} onInfo={() => setModal('info')} /></div>}
    </main>
    <Dialog open={modal !== null} onOpenChange={open => { if (!open && !busy) setModal(null); }}><DialogContent className="workspace-dialog"><DialogHeader><DialogTitle>{modal === 'create' ? '创建项目' : modal === 'rename' ? '重命名项目' : modal === 'delete' ? '删除项目' : modal === 'publish' ? '项目发布尚未配置' : '当前阶段与配置状态'}</DialogTitle><DialogDescription>{modal === 'create' || modal === 'rename' ? '项目名称将在服务器校验后保存到数据库。' : modal === 'delete' ? '此操作不可撤销：一个事务内删除项目及其全部消息和文件。' : '保留原生 AI 生成；本轮仅做只读运行预检，隔离运行与项目发布仍未配置。'}</DialogDescription></DialogHeader>
      {modal === 'create' || modal === 'rename' ? <form onSubmit={editProject} className="create-form"><label htmlFor="project-name">项目名称</label><input id="project-name" value={projectName} placeholder="例如：我的作品集" autoFocus disabled={busy} onChange={event => { setProjectName(event.target.value); setNameError(''); }} aria-invalid={!!nameError} />{nameError && <p className="form-error" role="alert">{nameError}</p>}<div className="dialog-actions"><button type="button" disabled={busy} className="secondary-button" onClick={() => setModal(null)}>取消</button><button type="submit" disabled={busy} className="primary-button">{busy ? <Loader2 size={15} className="spin" /> : <CheckCircle2 size={15} />}保存</button></div></form> : modal === 'delete' ? <><p>确认删除「{project?.name}」？</p>{nameError && <p className="form-error" role="alert">{nameError}</p>}<div className="dialog-actions"><button disabled={busy} className="secondary-button" onClick={() => setModal(null)}>取消</button><button disabled={busy} className="danger-button" onClick={removeProject}>{busy ? '正在删除…' : '确认永久删除'}</button></div></> : <><div className="service-list">{services.map(service => <div className="service-row" key={service.name}>{service.configured ? <CheckCircle2 size={17} /> : <TriangleAlert size={17} />}<div><strong>{service.name}</strong><p>{service.description}</p></div><span className={service.configured ? 'configured' : 'unconfigured'}>{service.configured ? '已接入' : '未配置'}</span></div>)}</div><p className="dialog-note">已保存的数据可在重新登录后加载；未发送草稿不持久化。代码区仅展示数据库文件内容，不执行代码。</p><div className="dialog-actions"><button className="primary-button" onClick={() => setModal(null)}>我知道了</button></div></>}
    </DialogContent></Dialog>
  </div>;
}
