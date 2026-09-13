import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  APIError,
  addStudentToClass,
  archiveSession,
  bulkAddStudents,
  closeSession,
  createClass,
  createOrganization,
  createSession,
  createStudent,
  getClass,
  getClasses,
  getOrganizations,
  getResults,
  getSession,
  getSessions,
  getStreamUrl,
  getStudents,
  removeStudentFromClass,
  startSession,
  submitAnswers,
  updateClass,
  updateOrganizationSettings,
  updateStudent,
} from './api'
import { setOrganizationId } from './api'
import { useAuth } from './App'
import type { AssessmentSession, ClassDetail, Classroom, Organization, QuestionStats, Results, Student } from './types'

const options = ['A', 'B', 'C', 'D'] as const

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function formatFullDate(value: string | null | undefined): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function PageHeading({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: React.ReactNode }) {
  return <div className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1>{description && <p>{description}</p>}</div>{action && <div className="heading-action">{action}</div>}</div>
}

function ErrorNotice({ message }: { message: string | null }) {
  return message ? <div className="notice notice-error" role="alert"><span>!</span>{message}</div> : null
}

function SuccessNotice({ message }: { message: string | null }) {
  return message ? <div className="notice notice-success" role="status"><span>✓</span>{message}</div> : null
}

function LoadingState({ label = '正在加载…' }: { label?: string }) {
  return <div className="inline-loading"><div className="spinner spinner-small" />{label}</div>
}

function EmptyState({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return <div className="empty-state"><div className="empty-icon">○</div><h3>{title}</h3><p>{description}</p>{action}</div>
}

export function LoginPage({ onLogin }: { onLogin: (email: string, password: string) => Promise<void> }) {
  const [email, setEmail] = useState('teacher@example.com')
  const [password, setPassword] = useState('demo-password')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await onLogin(email, password)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '登录失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return <div className="login-shell">
    <div className="login-visual"><div className="visual-grid" /><div className="login-visual-copy"><div className="brand-mark brand-mark-large">答</div><span className="eyebrow eyebrow-light">课堂数据工作台</span><h1>让每一次举手，<br /><em>都变成可见的学习反馈。</em></h1><p>从标准答案到实时学情，课堂中的每个关键变化，都有清晰的下一步。</p><div className="visual-pill"><span className="status-dot status-dot-live" />实时课堂已连接</div></div><div className="visual-footer">CLASSROOM ASSESSMENT PLATFORM · V1</div></div>
    <div className="login-panel"><div className="login-panel-inner"><div className="mobile-login-brand"><div className="brand-mark">答</div><strong>课堂答题台</strong></div><div className="login-heading"><span className="eyebrow">欢迎回来</span><h2>进入你的课堂工作台</h2><p>登录后管理班级、开始答题并查看实时反馈。</p></div><ErrorNotice message={error} /><form className="stack-form" onSubmit={handleSubmit}><label>邮箱地址<input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required /></label><label>密码<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label><button className="button button-primary button-full" disabled={submitting}>{submitting ? '正在进入…' : '进入工作台'}<span>→</span></button></form><div className="demo-hint"><span>演示环境</span><p>已填入演示教师账号，可直接登录体验完整课堂闭环。</p></div></div></div>
  </div>
}

export function DashboardPage() {
  const { me } = useAuth()
  const [classes, setClasses] = useState<Classroom[]>([])
  const [sessions, setSessions] = useState<AssessmentSession[]>([])
  const [activeResults, setActiveResults] = useState<Results | null>(null)
  const [loading, setLoading] = useState(true)
  const activeSession = sessions.find((session) => session.status === 'ACTIVE')

  useEffect(() => {
    Promise.all([getClasses(), getSessions()]).then(([loadedClasses, loadedSessions]) => {
      setClasses(loadedClasses)
      setSessions(loadedSessions)
    }).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!activeSession) return
    getResults(activeSession.id).then(setActiveResults).catch(() => setActiveResults(null))
  }, [activeSession?.id])

  if (loading) return <LoadingState />
  return <div className="page-stack">
    <PageHeading eyebrow="今天的课堂" title={`早上好，${me?.display_name || '老师'}`} description="把注意力放回课堂，数据交给答题台。" action={<Link to="/sessions/new" className="button button-primary">+ 新建课堂</Link>} />
    {activeSession && activeResults ? <section className="active-banner"><div className="active-banner-main"><div className="live-pulse"><span className="status-dot status-dot-live" />正在进行</div><h2>{activeSession.name || '未命名课堂'}</h2><p>{activeSession.class_name} · {activeSession.question_count} 道题 · {formatDate(activeSession.started_at)}</p></div><div className="active-metrics"><div><strong>{activeResults.submitted_count}</strong><span>已提交</span></div><div><strong>{activeResults.pending_count}</strong><span>待提交</span></div><div><strong>{activeResults.average_correct_rate}%</strong><span>当前正确率</span></div><Link to={`/sessions/${activeSession.id}/live`} className="button button-light">进入课堂 →</Link></div></section> : <section className="welcome-card"><div><span className="eyebrow">准备开始</span><h2>创建一场课堂答题</h2><p>选一个班级，录入标准答案，几十秒即可开始。</p><Link to="/sessions/new" className="button button-primary">创建第一场课堂</Link></div><div className="welcome-orbit"><span>答案</span><span>提交</span><span>反馈</span><div className="orbit-core">↗</div></div></section>}
    <section className="metric-grid"><MetricCard label="管理中的班级" value={classes.length} detail={`${classes.reduce((total, classroom) => total + classroom.student_count, 0)} 名学生`} icon="▦" /><MetricCard label="本月课堂" value={sessions.filter((session) => session.created_at.slice(0, 7) === new Date().toISOString().slice(0, 7)).length} detail="持续累积课堂数据" icon="◷" /><MetricCard label="最近课堂" value={sessions.length ? formatDate(sessions[0].created_at) : '—'} detail={sessions[0]?.class_name || '还没有历史记录'} icon="⌁" /></section>
    <div className="dashboard-columns"><section className="panel"><div className="panel-heading"><div><span className="eyebrow">快捷入口</span><h2>从这里继续</h2></div></div><div className="shortcut-grid"><Link to="/classes" className="shortcut-card"><span className="shortcut-icon shortcut-teal">▦</span><strong>管理班级</strong><span>添加学生、调班或归档</span><b>→</b></Link><Link to="/students" className="shortcut-card"><span className="shortcut-icon shortcut-orange">◉</span><strong>学生名册</strong><span>搜索和维护学生资料</span><b>→</b></Link><Link to="/sessions" className="shortcut-card"><span className="shortcut-icon shortcut-blue">◷</span><strong>历史课堂</strong><span>复盘每次答题表现</span><b>→</b></Link></div></section><section className="panel recent-panel"><div className="panel-heading"><div><span className="eyebrow">最近活动</span><h2>课堂记录</h2></div><Link to="/sessions" className="quiet-link">查看全部 →</Link></div>{sessions.slice(0, 4).map((session) => <Link className="recent-row" to={`/sessions/${session.id}/${session.status === 'ACTIVE' ? 'live' : 'results'}`} key={session.id}><span className={`session-mini-mark session-mini-${session.status.toLowerCase()}`}>{session.status === 'ACTIVE' ? '●' : '✓'}</span><div><strong>{session.name || '未命名课堂'}</strong><span>{session.class_name} · {formatDate(session.created_at)}</span></div><StatusBadge status={session.status} /></Link>)}{!sessions.length && <p className="muted-copy">还没有课堂记录。</p>}</section></div>
  </div>
}

function MetricCard({ label, value, detail, icon }: { label: string; value: string | number; detail: string; icon: string }) {
  return <div className="metric-card"><span className="metric-icon">{icon}</span><span className="eyebrow">{label}</span><strong>{value}</strong><small>{detail}</small></div>
}

function StatusBadge({ status }: { status: string }) {
  const label: Record<string, string> = { ACTIVE: '进行中', DRAFT: '草稿', CLOSED: '已结束', ARCHIVED: '已归档', SUBMITTED: '已提交', REVIEW_REQUIRED: '待复核', PENDING: '未提交' }
  return <span className={`status-badge status-badge-${status.toLowerCase()}`}><span />{label[status] || status}</span>
}

export function OrganizationsPage() {
  const { me, refreshProfile } = useAuth()
  const organizations = me?.memberships.map((membership) => membership.organization) || []
  const [selectedId, setSelectedId] = useState(organizations[0]?.id || '')
  const selected = organizations.find((organization) => organization.id === selectedId) || organizations[0]
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState({ name: '', organization_name: '', student_code_label: '学生编号' })
  const [settingsForm, setSettingsForm] = useState({ organization_name: '', student_code_label: '学生编号' })
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!selected) return
    setSettingsForm({ organization_name: selected.settings?.organization_name || selected.name, student_code_label: selected.settings?.student_code_label || '学生编号' })
  }, [selected?.id])

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault(); setError(null); setMessage(null)
    try {
      const organization = await createOrganization({ name: form.name, organization_name: form.organization_name || form.name, student_code_label: form.student_code_label })
      setOrganizationId(organization.id); setSelectedId(organization.id); setForm({ name: '', organization_name: '', student_code_label: '学生编号' }); setCreateOpen(false); await refreshProfile(); setMessage('机构已创建，已切换到新机构。')
    } catch (caught) { setError(caught instanceof Error ? caught.message : '创建机构失败') }
  }

  const handleSettings = async (event: FormEvent) => {
    event.preventDefault(); if (!selected) return; setError(null); setMessage(null)
    try { await updateOrganizationSettings(selected.id, { organization_name: settingsForm.organization_name, student_code_label: settingsForm.student_code_label }); await refreshProfile(); setMessage('机构配置已保存。') } catch (caught) { setError(caught instanceof Error ? caught.message : '保存失败') }
  }

  return <div className="page-stack"><PageHeading eyebrow="组织与品牌" title="机构设置" description="一套系统服务多个机构，名称和学生编号标签都可以独立配置。" action={<button className="button button-primary" onClick={() => setCreateOpen((value) => !value)}>+ 新建机构</button>} /><ErrorNotice message={error} /><SuccessNotice message={message} />{createOpen && <section className="panel form-panel"><div className="panel-heading"><div><span className="eyebrow">新机构</span><h2>创建一个新的课堂空间</h2></div></div><form className="form-grid" onSubmit={handleCreate}><label>机构名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：ABC Education" required /></label><label>展示名称（可选）<input value={form.organization_name} onChange={(event) => setForm({ ...form, organization_name: event.target.value })} placeholder="默认使用机构名称" /></label><label>学生编号标签<input value={form.student_code_label} onChange={(event) => setForm({ ...form, student_code_label: event.target.value })} required /></label><div className="form-actions"><button className="button button-primary">创建机构</button><button type="button" className="button button-ghost" onClick={() => setCreateOpen(false)}>取消</button></div></form></section>}<div className="two-column-layout"><section className="panel"><div className="panel-heading"><div><span className="eyebrow">我的机构</span><h2>选择工作空间</h2></div></div><div className="org-list">{organizations.map((organization) => <button className={`org-list-item ${selected?.id === organization.id ? 'org-list-item-active' : ''}`} key={organization.id} onClick={() => { setSelectedId(organization.id); setOrganizationId(organization.id) }}><span className="org-avatar">{organization.name.slice(0, 1)}</span><span><strong>{organization.name}</strong><small>{organization.settings?.student_code_label || '学生编号'}</small></span><span className="org-chevron">→</span></button>)}</div></section>{selected && <section className="panel"><div className="panel-heading"><div><span className="eyebrow">当前机构</span><h2>{selected.name}</h2></div><StatusBadge status={selected.status} /></div><form className="stack-form" onSubmit={handleSettings}><label>机构展示名称<input value={settingsForm.organization_name} onChange={(event) => setSettingsForm({ ...settingsForm, organization_name: event.target.value })} required /></label><label>学生编号标签<input value={settingsForm.student_code_label} onChange={(event) => setSettingsForm({ ...settingsForm, student_code_label: event.target.value })} required /></label><div className="settings-tip"><span>i</span>数据库字段始终保持统一的 <code>student_code</code>，这里只改变界面标签。</div><button className="button button-primary">保存配置</button></form></section>}</div></div>
}

export function ClassesPage() {
  const [classes, setClasses] = useState<Classroom[]>([])
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const refresh = () => getClasses().then(setClasses).catch((caught) => setError(caught instanceof Error ? caught.message : '加载班级失败')).finally(() => setLoading(false))
  useEffect(() => { void refresh() }, [])
  const handleCreate = async (event: FormEvent) => { event.preventDefault(); setError(null); try { await createClass(name); setName(''); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '创建班级失败') } }
  return <div className="page-stack"><PageHeading eyebrow="组织结构" title="班级管理" description="班级是课堂的起点，学生可以在班级之间流转，历史记录不会丢失。" action={<Link to="/sessions/new" className="button button-primary">+ 新建课堂</Link>} /><ErrorNotice message={error} /><section className="panel inline-create-panel"><div><span className="eyebrow">新建班级</span><h2>添加一个教学班</h2></div><form onSubmit={handleCreate}><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：初一 A 班" required /><button className="button button-primary">创建</button></form></section>{loading ? <LoadingState /> : classes.length ? <div className="class-grid">{classes.map((classroom) => <article className={`class-card ${classroom.status === 'ARCHIVED' ? 'class-card-archived' : ''}`} key={classroom.id}><div className="class-card-top"><span className="class-symbol">{classroom.name.slice(0, 1)}</span><StatusBadge status={classroom.status} /></div><h2>{classroom.name}</h2><p><strong>{classroom.student_count}</strong> 名在班学生</p><div className="class-card-actions"><Link to={`/classes/${classroom.id}`} className="button button-secondary">查看班级</Link>{classroom.status === 'ACTIVE' && <Link to={`/sessions/new?classId=${classroom.id}`} className="button button-quiet">开始课堂 →</Link>}</div></article>)}</div> : <EmptyState title="还没有班级" description="创建第一个班级，然后添加学生。" />}</div>
}

export function ClassDetailPage() {
  const { classId } = useParams<{ classId: string }>()
  const [detail, setDetail] = useState<ClassDetail | null>(null)
  const [allStudents, setAllStudents] = useState<Student[]>([])
  const [search, setSearch] = useState('')
  const [addOpen, setAddOpen] = useState(false)
  const [mode, setMode] = useState<'new' | 'existing' | 'bulk'>('new')
  const [newStudent, setNewStudent] = useState({ student_code: '', name: '' })
  const [existingId, setExistingId] = useState('')
  const [bulkText, setBulkText] = useState('')
  const [className, setClassName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const refresh = () => { if (classId) getClass(classId).then((value) => { setDetail(value); setClassName(value.name) }).catch((caught) => setError(caught instanceof Error ? caught.message : '加载班级失败')) }
  useEffect(refresh, [classId])
  const filteredStudents = detail?.students.filter((student) => `${student.name}${student.student_code}`.toLowerCase().includes(search.toLowerCase())) || []
  const loadAllStudents = () => getStudents().then(setAllStudents).catch((caught) => setError(caught instanceof Error ? caught.message : '加载学生失败'))
  const openAdd = (nextMode: 'new' | 'existing' | 'bulk') => { setMode(nextMode); setAddOpen(true); setError(null); setMessage(null); if (nextMode === 'existing') loadAllStudents() }
  const handleNew = async (event: FormEvent) => { event.preventDefault(); if (!classId) return; setError(null); try { const student = await createStudent(newStudent); await addStudentToClass(classId, student.id); setNewStudent({ student_code: '', name: '' }); setAddOpen(false); setMessage('学生已创建并加入班级。'); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '添加学生失败') } }
  const handleExisting = async (event: FormEvent) => { event.preventDefault(); if (!classId || !existingId) return; setError(null); try { await addStudentToClass(classId, existingId); setAddOpen(false); setMessage('学生已加入班级。'); refresh() } catch (caught) { if (caught instanceof APIError && caught.status === 409 && window.confirm('该学生当前在其他班级。是否确认调班到本班？原班级历史记录会保留。')) { try { await addStudentToClass(classId, existingId, true); setAddOpen(false); setMessage('学生已调入本班，原班级历史记录已保留。'); refresh() } catch (retry) { setError(retry instanceof Error ? retry.message : '调班失败') } } else setError(caught instanceof Error ? caught.message : '加入班级失败') } }
  const handleBulk = async (event: FormEvent) => { event.preventDefault(); if (!classId) return; const students = bulkText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => { const parts = line.split(/[,\t，]/).map((part) => part.trim()); return { student_code: parts[0] || '', name: parts.slice(1).join(' ') || parts[0] || '' } }).filter((student) => student.student_code && student.name); if (!students.length) { setError('请按“学生编号,姓名”每行填写一名学生。'); return } setError(null); try { await bulkAddStudents(classId, students); setBulkText(''); setAddOpen(false); setMessage(`已批量加入 ${students.length} 名学生。`); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '批量添加失败') } }
  const handleRemove = async (student: Student) => { if (!classId || !window.confirm(`确认将 ${student.name} 移出 ${detail?.name}？学生资料和历史成绩会保留。`)) return; try { await removeStudentFromClass(classId, student.id); setMessage(`${student.name} 已移出班级，历史记录保留。`); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '移出失败') } }
  const handleRename = async (event: FormEvent) => { event.preventDefault(); if (!classId || !className.trim() || className === detail?.name) return; try { await updateClass(classId, { name: className.trim() }); setMessage('班级名称已更新。'); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '保存班级失败') } }
  if (!detail) return <LoadingState />
  return <div className="page-stack"><PageHeading eyebrow="班级详情" title={detail.name} description={`${detail.student_count} 名在班学生 · 班级成员可随时调动，历史课堂按快照保存。`} action={<div className="button-row"><Link to={`/sessions/new?classId=${detail.id}`} className="button button-primary">开始课堂 →</Link><button className="button button-secondary" onClick={() => openAdd('existing')}>+ 添加学生</button></div>} /><ErrorNotice message={error} /><SuccessNotice message={message} /><section className="panel class-toolbar"><form onSubmit={handleRename} className="rename-form"><label>班级名称<input value={className} onChange={(event) => setClassName(event.target.value)} /></label><button className="button button-quiet" disabled={className === detail.name}>保存</button></form><div className="student-tools"><label className="search-field"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索姓名或学生编号" /></label><div className="button-row"><button className="button button-quiet" onClick={() => openAdd('bulk')}>批量添加</button><button className="button button-quiet" onClick={() => openAdd('new')}>新建学生</button></div></div></section>{addOpen && <section className="panel add-student-panel"><div className="panel-heading"><div><span className="eyebrow">班级成员</span><h2>添加学生</h2></div><button className="icon-button" onClick={() => setAddOpen(false)} aria-label="关闭">×</button></div><div className="segmented-control"><button className={mode === 'new' ? 'selected' : ''} onClick={() => setMode('new')}>新建学生</button><button className={mode === 'existing' ? 'selected' : ''} onClick={() => { setMode('existing'); loadAllStudents() }}>已有学生 / 调班</button><button className={mode === 'bulk' ? 'selected' : ''} onClick={() => setMode('bulk')}>批量添加</button></div>{mode === 'new' && <form className="form-grid" onSubmit={handleNew}><label>学生编号<input value={newStudent.student_code} onChange={(event) => setNewStudent({ ...newStudent, student_code: event.target.value })} placeholder="例如：S001" required /></label><label>姓名<input value={newStudent.name} onChange={(event) => setNewStudent({ ...newStudent, name: event.target.value })} placeholder="例如：张三" required /></label><div className="form-actions"><button className="button button-primary">创建并加入</button></div></form>}{mode === 'existing' && <form className="form-grid" onSubmit={handleExisting}><label className="wide-label">选择学生<select value={existingId} onChange={(event) => setExistingId(event.target.value)} required><option value="">请选择已有学生</option>{allStudents.filter((student) => !detail.students.some((current) => current.id === student.id)).map((student) => <option key={student.id} value={student.id}>{student.name} · {student.student_code}</option>)}</select></label><p className="form-hint">如果学生正在另一个班级，提交后会要求确认调班；原班级的历史课堂和成绩不会被删除。</p><div className="form-actions"><button className="button button-primary">加入 / 调班</button></div></form>}{mode === 'bulk' && <form className="stack-form" onSubmit={handleBulk}><label>每行一名学生，格式：学生编号,姓名<textarea rows={5} value={bulkText} onChange={(event) => setBulkText(event.target.value)} placeholder={'S001,张三\nS002,李四\nS003,王五'} /></label><div className="form-actions"><button className="button button-primary">批量加入</button></div></form>}</section>}<section className="panel"><div className="panel-heading"><div><span className="eyebrow">当前成员</span><h2>{filteredStudents.length} 名学生</h2></div><span className="muted-copy">移出不会删除学生</span></div>{filteredStudents.length ? <div className="student-table"><div className="student-table-head"><span>学生</span><span>编号</span><span>状态</span><span /></div>{filteredStudents.map((student) => <div className="student-table-row" key={student.id}><div className="student-identity"><span className="student-avatar">{student.name.slice(0, 1)}</span><strong>{student.name}</strong></div><span className="student-code">{student.student_code}</span><StatusBadge status={student.status} /><button className="row-action" onClick={() => handleRemove(student)}>移出</button></div>)}</div> : <EmptyState title={search ? '没有匹配学生' : '班级还没有学生'} description={search ? '换个姓名或学生编号试试。' : '添加第一名学生后，就可以创建课堂。'} action={!search ? <button className="button button-secondary" onClick={() => openAdd('new')}>新建学生</button> : undefined} />}</section></div>
}

export function StudentsPage() {
  const [students, setStudents] = useState<Student[]>([])
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ student_code: '', name: '' })
  const [error, setError] = useState<string | null>(null)
  const refresh = () => getStudents(search).then(setStudents).catch((caught) => setError(caught instanceof Error ? caught.message : '加载学生失败'))
  useEffect(() => { void refresh() }, [search])
  const handleCreate = async (event: FormEvent) => { event.preventDefault(); try { await createStudent(form); setForm({ student_code: '', name: '' }); setOpen(false); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '创建学生失败') } }
  return <div className="page-stack"><PageHeading eyebrow="全局名册" title="学生" description="学生资料独立于班级，调班、移出和重新加入都不会影响历史答题记录。" action={<button className="button button-primary" onClick={() => setOpen((value) => !value)}>+ 新建学生</button>} /><ErrorNotice message={error} />{open && <section className="panel form-panel"><div className="panel-heading"><div><span className="eyebrow">新学生</span><h2>建立学生资料</h2></div></div><form className="form-grid" onSubmit={handleCreate}><label>学生编号<input value={form.student_code} onChange={(event) => setForm({ ...form, student_code: event.target.value })} required /></label><label>姓名<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label><div className="form-actions"><button className="button button-primary">保存学生</button></div></form></section>}<section className="panel"><div className="panel-heading"><div><span className="eyebrow">学生总表</span><h2>{students.length} 名学生</h2></div><label className="search-field search-field-wide"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索姓名或学生编号" /></label></div>{students.length ? <div className="student-table"><div className="student-table-head"><span>学生</span><span>编号</span><span>状态</span><span /></div>{students.map((student) => <div className="student-table-row" key={student.id}><div className="student-identity"><span className="student-avatar">{student.name.slice(0, 1)}</span><strong>{student.name}</strong></div><span className="student-code">{student.student_code}</span><StatusBadge status={student.status} /><span className="muted-copy">资料已保留</span></div>)}</div> : <EmptyState title="没有找到学生" description="可以新建学生，或调整搜索条件。" />}</section></div>
}

export function NewSessionPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [classes, setClasses] = useState<Classroom[]>([])
  const [classId, setClassId] = useState(searchParams.get('classId') || '')
  const [name, setName] = useState('')
  const [questionCount, setQuestionCount] = useState(5)
  const [answers, setAnswers] = useState<string[]>(Array(5).fill('A'))
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => { getClasses().then((loaded) => { setClasses(loaded); if (!classId && loaded[0]) setClassId(loaded[0].id) }) }, [])
  const resizeQuestions = (value: number) => { const next = Math.min(100, Math.max(1, value || 1)); setQuestionCount(next); setAnswers((current) => Array.from({ length: next }, (_, index) => current[index] || 'A')) }
  const handleSubmit = async (event: FormEvent) => { event.preventDefault(); setError(null); setSubmitting(true); try { const session = await createSession({ class_id: classId, name: name.trim() || null, question_count: questionCount, answer_keys: answers.map((value, index) => ({ question_no: index + 1, value })) }); await startSession(session.id); navigate(`/sessions/${session.id}/live`) } catch (caught) { setError(caught instanceof Error ? caught.message : '创建课堂失败') } finally { setSubmitting(false) } }
  return <div className="page-stack narrow-page"><PageHeading eyebrow="新课堂" title="创建一次答题课堂" description="选班级、填名称、录入标准答案，然后直接开始。" /><ErrorNotice message={error} /><form className="session-builder" onSubmit={handleSubmit}><section className="panel builder-section"><div className="section-number">01</div><div className="builder-content"><span className="eyebrow">课堂信息</span><h2>这次要和哪个班一起答题？</h2><div className="form-grid"><label>选择班级<select value={classId} onChange={(event) => setClassId(event.target.value)} required><option value="">请选择班级</option>{classes.filter((classroom) => classroom.status === 'ACTIVE').map((classroom) => <option value={classroom.id} key={classroom.id}>{classroom.name} · {classroom.student_count} 人</option>)}</select></label><label>课堂名称 <span className="optional">可选</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：阅读 A 篇" /></label></div></div></section><section className="panel builder-section"><div className="section-number">02</div><div className="builder-content"><span className="eyebrow">题目设置</span><h2>录入标准答案</h2><label className="question-count-field">题目数量<input type="number" min={1} max={100} value={questionCount} onChange={(event) => resizeQuestions(Number(event.target.value))} /><span>道选择题</span></label><div className="answer-key-list">{answers.map((answer, index) => <div className="answer-key-row" key={index}><span className="question-index">{String(index + 1).padStart(2, '0')}</span><span className="question-label">第 {index + 1} 题</span><div className="answer-options">{options.map((option) => <button type="button" key={option} className={answer === option ? 'answer-option answer-option-selected' : 'answer-option'} onClick={() => setAnswers((current) => current.map((value, itemIndex) => itemIndex === index ? option : value))}>{option}</button>)}</div></div>)}</div></div></section><div className="builder-footer"><Link to="/dashboard" className="button button-ghost">取消</Link><button className="button button-primary button-large" disabled={submitting || !classId}>{submitting ? '正在创建…' : '开始答题课堂 →'}</button></div></form></div>
}

export function SessionsPage() {
  const [sessions, setSessions] = useState<AssessmentSession[]>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => { getSessions().then(setSessions).finally(() => setLoading(false)) }, [])
  return <div className="page-stack"><PageHeading eyebrow="课堂数据" title="课堂记录" description="每次课堂都会保存为独立快照，方便课后复盘与持续积累。" action={<Link to="/sessions/new" className="button button-primary">+ 新建课堂</Link>} />{loading ? <LoadingState /> : sessions.length ? <section className="panel session-history"><div className="history-head"><span>课堂</span><span>班级</span><span>状态</span><span>创建时间</span><span /></div>{sessions.map((session) => <div className="history-row" key={session.id}><div className="history-title"><span className={`session-mini-mark session-mini-${session.status.toLowerCase()}`}>{session.status === 'ACTIVE' ? '●' : '✓'}</span><div><strong>{session.name || '未命名课堂'}</strong><small>{session.question_count} 道题</small></div></div><span>{session.class_name}</span><StatusBadge status={session.status} /><span className="muted-copy">{formatDate(session.created_at)}</span><div className="history-actions">{session.status === 'ACTIVE' ? <Link to={`/sessions/${session.id}/live`} className="button button-quiet">进入课堂 →</Link> : <Link to={`/sessions/${session.id}/results`} className="button button-quiet">查看结果</Link>}</div></div>)}</section> : <EmptyState title="还没有课堂记录" description="创建一场课堂，实时学情会从这里开始积累。" action={<Link to="/sessions/new" className="button button-primary">创建课堂</Link>} />}</div>
}

export function LiveSessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const [result, setResult] = useState<Results | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [connection, setConnection] = useState<'connected' | 'reconnecting'>('reconnecting')
  const [lastUpdated, setLastUpdated] = useState(new Date())
  const [selectedStudent, setSelectedStudent] = useState('')
  const [mockAnswers, setMockAnswers] = useState<Record<number, string>>({})
  const [reviewRequired, setReviewRequired] = useState(false)
  const [expanded, setExpanded] = useState<number[]>([])
  const [submitting, setSubmitting] = useState(false)
  const refresh = (quiet = false) => { if (!sessionId) return Promise.resolve(); if (!quiet) setLoading(true); return getResults(sessionId).then((loaded) => { setResult(loaded); setLastUpdated(new Date()); setError(null) }).catch((caught) => setError(caught instanceof Error ? caught.message : '加载课堂数据失败')).finally(() => { if (!quiet) setLoading(false) }) }
  useEffect(() => { refresh(); if (!sessionId) return; const source = new EventSource(getStreamUrl(sessionId)); const onUpdate = () => refresh(true); source.addEventListener('session.update', onUpdate); source.onopen = () => setConnection('connected'); source.onerror = () => setConnection('reconnecting'); return () => { source.removeEventListener('session.update', onUpdate); source.close() } }, [sessionId])
  useEffect(() => { if (!result) return; const pending = result.students.filter((student) => student.status === 'PENDING'); setSelectedStudent((current) => current && pending.some((student) => student.student_id === current) ? current : pending[0]?.student_id || result.students[0]?.student_id || '') }, [result])
  useEffect(() => { if (!result) return; setMockAnswers(Object.fromEntries(result.questions.map((question) => [question.question_no, 'A']))) }, [result?.session.id])
  const pendingStudents = result?.students.filter((student) => student.status === 'PENDING') || []
  const handleMockSubmit = async (event: FormEvent) => { event.preventDefault(); if (!sessionId || !selectedStudent) return; setSubmitting(true); try { await submitAnswers(sessionId, { student_id: selectedStudent, answers: Object.entries(mockAnswers).map(([question_no, value]) => ({ question_no: Number(question_no), value })), review_required: reviewRequired }); await refresh(true) } catch (caught) { setError(caught instanceof Error ? caught.message : '模拟提交失败') } finally { setSubmitting(false) } }
  const handleClose = async () => { if (!sessionId || !window.confirm('确认结束这场课堂？结束后不再接受新的提交，但仍可查看历史结果。')) return; try { await closeSession(sessionId); await refresh(true) } catch (caught) { setError(caught instanceof Error ? caught.message : '结束课堂失败') } }
  const toggleOption = (questionNo: number) => setExpanded((current) => current.includes(questionNo) ? current.filter((item) => item !== questionNo) : [...current, questionNo])
  if (loading && !result) return <LoadingState label="正在连接课堂数据…" />
  if (!result) return <><ErrorNotice message={error || '课堂不存在'} /><Link to="/sessions" className="button button-secondary">返回课堂记录</Link></>
  const session = result.session
  return <div className="page-stack live-page"><div className="live-page-header"><div><div className="breadcrumb"><Link to="/sessions">课堂记录</Link><span>/</span>{session.class_name}</div><div className="live-title-line"><h1>{session.name || '未命名课堂'}</h1><StatusBadge status={session.status} /></div><p>{session.class_name} · {session.question_count} 道题 · {formatFullDate(session.started_at || session.created_at)}</p></div><div className="button-row"><span className={`connection-state connection-${connection}`}><span />{connection === 'connected' ? '实时连接中' : '正在重连'}</span>{session.status === 'ACTIVE' ? <button className="button button-danger" onClick={handleClose}>结束课堂</button> : <Link to={`/sessions/${session.id}/results`} className="button button-primary">查看完整结果 →</Link>}</div></div><ErrorNotice message={error} /><section className="live-summary-grid"><LiveSummary label="全班学生" value={result.participant_count} hint="本场课堂名单" tone="neutral" /><LiveSummary label="已提交" value={result.submitted_count} hint={`${result.participant_count ? Math.round((result.submitted_count / result.participant_count) * 100) : 0}% 到达`} tone="green" /><LiveSummary label="未提交" value={result.pending_count} hint="需要关注" tone="gray" /><LiveSummary label="待复核" value={result.review_required_count} hint="识别或答题需确认" tone="orange" /></section><section className="panel status-panel"><div className="panel-heading"><div><span className="eyebrow">课堂进度</span><h2>学生提交状态</h2></div><span className="live-updated"><span className="status-dot status-dot-live" />刚刚更新 {lastUpdated.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span></div><div className="student-status-grid">{result.students.map((student) => <div className={`student-status-card status-card-${student.status.toLowerCase()}`} key={student.student_id}><div className="student-status-top"><span className="student-avatar">{student.student_name.slice(0, 1)}</span><span className="status-card-icon">{student.status === 'PENDING' ? '○' : student.status === 'REVIEW_REQUIRED' ? '!' : '✓'}</span></div><strong>{student.student_name}</strong><small>{student.student_code}</small><span className="status-card-label">{student.status === 'PENDING' ? '未提交' : student.status === 'REVIEW_REQUIRED' ? '待复核' : '已提交'}</span></div>)}</div></section><div className="live-main-grid"><section className="panel question-stats-panel"><div className="panel-heading"><div><span className="eyebrow">实时分布</span><h2>每题答题情况</h2></div><span className="muted-copy">点击选项查看学生</span></div><div className="question-stats-list">{result.questions.map((question) => <QuestionStatCard key={question.question_no} question={question} expanded={expanded.includes(question.question_no)} onToggle={() => toggleOption(question.question_no)} />)}</div></section><section className="panel mock-panel"><div className="panel-heading"><div><span className="eyebrow">Development / Test</span><h2>模拟提交</h2></div><span className="dev-badge">MOCK</span></div>{session.status === 'ACTIVE' ? <form className="stack-form" onSubmit={handleMockSubmit}><label>选择学生<select value={selectedStudent} onChange={(event) => setSelectedStudent(event.target.value)}>{pendingStudents.length ? pendingStudents.map((student) => <option key={student.student_id} value={student.student_id}>{student.student_name} · {student.student_code}</option>) : result.students.map((student) => <option key={student.student_id} value={student.student_id}>{student.student_name} · {student.student_code}</option>)}</select></label><div className="mock-answer-list">{result.questions.map((question) => <label key={question.question_no}>第 {question.question_no} 题<select value={mockAnswers[question.question_no] || 'A'} onChange={(event) => setMockAnswers((current) => ({ ...current, [question.question_no]: event.target.value }))}>{options.map((option) => <option value={option} key={option}>{option}</option>)}</select></label>)}</div><label className="check-row"><input type="checkbox" checked={reviewRequired} onChange={(event) => setReviewRequired(event.target.checked)} /><span>标记为待复核</span></label><button className="button button-primary button-full" disabled={submitting || !result.students.length}>{submitting ? '提交中…' : '模拟提交这份答题'}</button><p className="form-hint">此工具只用于开发联调；Android 后续使用同一套 Submission API。</p></form> : <div className="closed-callout"><span>✓</span><strong>课堂已结束</strong><p>提交入口已关闭。你仍可以查看本场完整结果。</p><Link to={`/sessions/${session.id}/results`} className="button button-secondary">进入结果页</Link></div>}</section></div></div>
}

function LiveSummary({ label, value, hint, tone }: { label: string; value: string | number; hint: string; tone: string }) { return <div className={`live-summary live-summary-${tone}`}><span className="eyebrow">{label}</span><strong>{value}</strong><small>{hint}</small></div> }

function QuestionStatCard({ question, expanded, onToggle }: { question: QuestionStats; expanded: boolean; onToggle: () => void }) {
  return <article className="question-stat-card"><div className="question-stat-header"><div className="question-number">Q{question.question_no}</div><div><strong>第 {question.question_no} 题</strong><span>正确答案 <b className="answer-key-chip">{question.correct_answer}</b></span></div><div className="question-rate"><strong>{question.correct_rate}%</strong><span>正确率</span></div></div><div className="question-distribution">{options.map((option) => { const count = question.counts[option]; const isCorrect = option === question.correct_answer; return <button className={`distribution-option ${isCorrect ? 'distribution-correct' : ''} ${expanded ? 'distribution-expanded' : ''}`} key={option} onClick={onToggle}><span className="distribution-label"><b>{option}</b>{isCorrect && <em>正确</em>}</span><span className="distribution-bar"><i style={{ width: `${question.answered_count ? (count / question.answered_count) * 100 : 0}%` }} /></span><span className="distribution-count">{count}<small>人</small></span></button> })}</div><div className="question-stat-foot"><span>已作答 {question.answered_count} / {question.submitted_count}</span><button className="option-expand-link" onClick={onToggle}>{expanded ? '收起姓名' : '点击选项查看学生'} <span>{expanded ? '↑' : '↓'}</span></button></div>{expanded && <div className="option-student-list">{options.map((option) => question.students_by_option[option].length ? <div key={option}><b>{option}</b><span>{question.students_by_option[option].join('、')}</span></div> : null)}{!options.some((option) => question.students_by_option[option].length) && <span className="muted-copy">暂无已作答学生</span>}</div>}</article>
}

export function ResultsPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const [result, setResult] = useState<Results | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [archiving, setArchiving] = useState(false)
  useEffect(() => { if (sessionId) getResults(sessionId).then(setResult).catch((caught) => setError(caught instanceof Error ? caught.message : '加载结果失败')) }, [sessionId])
  const handleArchive = async () => { if (!sessionId || !window.confirm('确认归档这场课堂？归档后仍可查看，但不再作为进行中记录。')) return; setArchiving(true); try { const archived = await archiveSession(sessionId); setResult((current) => current ? { ...current, session: archived } : current) } catch (caught) { setError(caught instanceof Error ? caught.message : '归档失败') } finally { setArchiving(false) } }
  if (!result) return <div className="page-stack"><ErrorNotice message={error} /><LoadingState /></div>
  const { session } = result
  return <div className="page-stack"><PageHeading eyebrow="课堂复盘" title={session.name || '未命名课堂'} description={`${session.class_name} · ${formatFullDate(session.ended_at || session.created_at)}`} action={<div className="button-row"><Link to="/sessions" className="button button-secondary">返回记录</Link>{session.status === 'CLOSED' && <button className="button button-primary" onClick={handleArchive} disabled={archiving}>{archiving ? '归档中…' : '归档课堂'}</button>}</div>} /><ErrorNotice message={error} /><section className="result-hero"><div><span className="eyebrow eyebrow-light">本场课堂总览</span><h2>全班答题完成度 <em>{result.participant_count ? Math.round((result.submitted_count / result.participant_count) * 100) : 0}%</em></h2><p>{result.submitted_count} 名学生提交，{result.pending_count} 名未提交</p></div><div className="result-hero-metrics"><div><strong>{result.average_correct_rate}%</strong><span>平均正确率</span></div><div><strong>{result.review_required_count}</strong><span>待复核</span></div></div></section><section className="result-question-grid">{result.questions.map((question) => <QuestionStatCard key={question.question_no} question={question} expanded={false} onToggle={() => {}} />)}</section><section className="panel result-students-panel"><div className="panel-heading"><div><span className="eyebrow">个人明细</span><h2>学生答题结果</h2></div><span className="muted-copy">姓名仅在结果页展示</span></div><div className="result-table"><div className="result-table-head"><span>学生</span><span>状态</span><span>每题答案</span><span>正确数</span></div>{result.students.map((student) => <div className="result-table-row" key={student.student_id}><div className="student-identity"><span className="student-avatar">{student.student_name.slice(0, 1)}</span><div><strong>{student.student_name}</strong><small>{student.student_code}</small></div></div><StatusBadge status={student.status} /><div className="answer-pill-row">{session.questions.map((question) => <span className={`answer-pill ${student.answers?.[question.question_no] === question.correct_answer ? 'answer-pill-correct' : ''}`} key={question.question_no}>{student.answers?.[question.question_no] || '—'}</span>)}</div><strong>{student.answers ? Object.entries(student.answers).filter(([questionNo, value]) => session.questions.find((question) => question.question_no === Number(questionNo))?.correct_answer === value).length : 0} / {session.question_count}</strong></div>)}</div></section></div>
}
