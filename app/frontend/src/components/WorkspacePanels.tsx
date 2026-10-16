import { ArrowUp, Box, ChevronDown, ChevronRight, CircleHelp, Code2, FileCode2, Folder, FolderTree, History, LayoutGrid, Loader2, MessageSquare, Monitor, Plus, ShieldCheck, Sparkles, TriangleAlert } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import PreviewReadiness from '@/components/PreviewReadiness';
import '@/preview-readiness.css';
import type { Project, WorkspaceView } from '@/lib/workspace';

interface SidebarProps {
  projects: Project[];
  activeId: string;
  filesOpen: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onFiles: () => void;
  onInfo: () => void;
}

export function ProjectSidebar({ projects, activeId, filesOpen, onSelect, onCreate, onFiles, onInfo }: SidebarProps) {
  const activeProject = projects.find(project => project.id === activeId);
  return <>
    <div className="sidebar-brand"><span className="brand-mark"><Box size={22} /></span><span>Atoms Demo<small>应用开发工作台</small></span></div>
    <div className="workspace-label"><span className="workspace-avatar">A</span><div>个人工作空间<small>数据库项目 · 第四阶段 A</small></div><span className="phase-tag">04</span></div>
    <button className="nav-item selected" onClick={() => onSelect(activeId)}><LayoutGrid size={17} />项目工作台<span className="nav-count">{projects.length}</span></button>
    <div className="section-label"><span>我的项目</span><button className="icon-button" aria-label="创建项目" onClick={onCreate}><Plus size={16} /></button></div>
    <nav aria-label="项目列表" className="project-list">{projects.map(project => <button key={project.id} className={`project-item ${project.id === activeId ? 'active' : ''}`} aria-current={project.id === activeId ? 'page' : undefined} onClick={() => onSelect(project.id)}><Folder size={16} /><span>{project.name}</span>{project.id === activeId && <span className="green-dot" />}</button>)}</nav>
    <button className="new-project" onClick={onCreate}><Plus size={16} />新建项目</button>
    <div className="sidebar-divider" />
    <button className="nav-item" aria-expanded={filesOpen} onClick={onFiles}><FolderTree size={17} />项目文件{filesOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button>
    {filesOpen && <div className="file-empty"><Folder size={19} /><span>{activeProject?.files.length ? '已保存文件' : '暂无文件'}</span>{activeProject?.files.map(file => <button key={file.id} onClick={() => document.getElementById("tab-Code")?.click()} title={file.path}>{file.path}</button>)}{!activeProject?.files.length && <small>发送需求后生成并保存文件。</small>}</div>}
    <div className="sidebar-bottom"><div className="local-note"><ShieldCheck size={16} /><div>私有数据库项目<small>已保存消息可在登录后恢复</small></div></div><button className="nav-item" onClick={onInfo}><CircleHelp size={17} />配置与阶段说明<ChevronRight size={15} /></button><div className="sidebar-footer"><span className="user-avatar">我</span><span>个人工作空间<small>原生认证</small></span><span className="small-label">私有</span></div></div>
  </>;
}

interface ChatProps {
  project: Project;
  busy: boolean;
  error: string;
  onDraft: (value: string) => void;
  onSend: () => void;
  onInfo: () => void;
}
const suggestions = ['构建一个简洁的个人作品集', '设计一个任务管理应用', '创建一个数据分析仪表盘'];

export function ConversationPanel({ project, busy, error, onDraft, onSend, onInfo }: ChatProps) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'nearest' }); }, [project.messages.length, busy]);
  return <section className="chat-panel" aria-label="AI 对话区">
    <div className="panel-heading"><span><MessageSquare size={16} />AI 对话</span><span className="small-label">需求工作区</span></div>
    <div className="messages">
      {project.messages.length === 0 ? <div className="chat-welcome"><div className="welcome-symbol"><Sparkles size={26} /></div><span className="eyebrow">从一个想法开始</span><h1>你想构建什么？</h1><p>用自然语言描述你的应用。<br />基于当前项目生成或增量修改代码。</p><div className="suggestions">{suggestions.map((text, index) => <button key={text} onClick={() => onDraft(text)}><span>{index === 0 ? <FileCode2 size={16} /> : index === 1 ? <LayoutGrid size={16} /> : <Monitor size={16} />}{text}</span><ChevronRight size={15} /></button>)}</div><span className="welcome-disclaimer">示例仅填入输入框，不会自动生成应用</span></div> : <div className="message-list">{project.messages.map(message => <article key={message.id} className={`message ${message.role}`}><div className="message-meta"><span>{message.role === 'user' ? '你' : message.role === 'assistant' ? 'AI · 文件变更说明' : '系统状态 · 非 AI 回复'}</span><time>{message.time}</time></div><p>{message.content}</p>{message.role === 'system' && <span className="error-tag">历史系统记录</span>}</article>)}<div ref={endRef} /></div>}
    {busy && <div className="busy-message" role="status"><Loader2 size={16} className="spin" />正在请求模型并校验、保存结果…</div>}
    </div>
    <div className="composer-area"><div className="service-notice"><span className="amber-dot" /><span>原生 AI 接口 · 仅保存代码</span><button onClick={onInfo}>查看说明<ChevronRight size={13} /></button></div><form className="composer" onSubmit={event => { event.preventDefault(); onSend(); }}><label className="sr-only" htmlFor="requirement">应用需求</label><textarea id="requirement" placeholder="描述你的应用、功能或想要的修改…" value={project.draft} disabled={busy} onChange={event => onDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSend(); } }} /><div className="composer-bottom"><span><Sparkles size={13} />React 网页文件 · 最多 80 个 / 20 万字符</span><button className="send-button" type="submit" disabled={busy} aria-label="发送需求并生成代码">{busy ? <Loader2 size={17} className="spin" /> : <ArrowUp size={19} />}</button></div></form><div className="composer-caption"><span>Enter 发送 · Shift + Enter 换行</span><span>{project.draft.length}/4000</span></div>{error && <p className="form-error" role="alert">{error}</p>}</div>
  </section>;
}

interface PreviewProps {
  project: Project;
  view: WorkspaceView;
  onView: (view: WorkspaceView) => void;
  onInfo: () => void;
}
const views: WorkspaceView[] = ['Preview', 'Code', 'History'];
const tabIcons = { Preview: Monitor, Code: Code2, History };

export function PreviewPanel({ project, view, onView, onInfo }: PreviewProps) {
  const [fileId, setFileId] = useState('');
  const selectedFile = project.files.find(file => file.id === fileId) || project.files[0];
  return <section className="preview-panel" aria-label="应用预览区"><div className="preview-tabs" role="tablist" aria-label="应用视图">{views.map((tab, index) => { const Icon = tabIcons[tab]; return <button role="tab" id={`tab-${tab}`} aria-controls="view-content" aria-selected={view === tab} tabIndex={view === tab ? 0 : -1} key={tab} className={view === tab ? 'active' : ''} onClick={() => onView(tab)} onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3; onView(views[next]); document.getElementById(`tab-${views[next]}`)?.focus(); } }}><Icon size={16} />{tab}</button>; })}<span className="preview-mode">应用输出</span></div>
    <div id="view-content" role="tabpanel" aria-labelledby={`tab-${view}`} className={`view-content ${view === 'Preview' ? 'preview-grid' : ''}`}>
      {view === 'Preview' ? <PreviewReadiness project={project} /> : view === 'Code' && project.files.length > 0 ? <div className="code-content"><label htmlFor="code-file">数据库文件</label><select id="code-file" value={selectedFile.id} onChange={event => setFileId(event.target.value)}>{project.files.map(file => <option key={file.id} value={file.id}>{file.path}</option>)}</select><pre><code>{selectedFile.content}</code></pre><p className="dialog-note">只读展示，不执行代码。</p></div> : view === 'History' ? <div className="history-content"><div className="history-header"><h2>操作历史</h2><p>由数据库项目和消息恢复的记录，不是完整审计日志或代码版本。</p></div>{project.history.map(entry => <div className="history-entry" key={entry.id}><span className={entry.kind === 'error' ? 'history-icon error' : 'history-icon'}>{entry.kind === 'error' ? <TriangleAlert size={15} /> : <Plus size={15} />}</span><div><p>{entry.label}</p><time>{entry.time}</time></div><span className="small-label">{entry.kind === 'saved' ? '已保存' : '未执行'}</span></div>)}</div> : <div className="preview-empty"><div className="preview-illustration">{view === 'Preview' ? <Monitor size={38} strokeWidth={1.3} /> : <FileCode2 size={38} strokeWidth={1.3} />}<span className="empty-plus"><Plus size={15} /></span></div><span className="empty-pill">{view === 'Preview' ? '等待运行环境' : '等待代码生成'}</span><h2>{view === 'Preview' ? '运行环境尚未配置' : '还没有应用代码'}</h2><p>{view === 'Preview' ? '生成代码并连接安全运行环境后，\n即可在这里查看真实的网页预览。' : '发送需求后，模型将基于当前项目生成文件。\n只有校验与数据库保存成功后才会显示代码。'}</p><button className="secondary-button" onClick={onInfo}><CircleHelp size={15} />查看配置状态</button><div className="preview-steps"><span><span>1</span>描述需求</span><i /><span><span>2</span>生成代码</span><i /><span><span>3</span>运行预览</span></div><small>当前支持需求、代码生成与保存；运行环境尚未配置</small></div>}
    </div><div className="preview-status"><span><span className="amber-dot" />运行环境未配置</span><span>无构建 · 无部署</span></div>
  </section>;
}
