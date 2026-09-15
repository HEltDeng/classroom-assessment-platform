import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  APIError,
  addStudentToClass,
  archiveSession,
  bulkAddStudents,
  bulkAttachStudents,
  closeSession,
  createCourseDay,
  confirmStudentImport,
  createClass,
  createOrganization,
  createSession,
  createStudent,
  createSubject,
  createTeacher,
  createTimeSlot,
  downloadFile,
  exportClass,
  exportStudentImportTemplate,
  exportSessionReport,
  exportStudents,
  getClass,
  getClasses,
  getCourseDays,
  getOrganizationId,
  getOrganizations,
  getResults,
  getSession,
  getSessions,
  getStreamUrl,
  getStudents,
  getSubjects,
  getTeachers,
  getTimeSlots,
  removeStudentFromClass,
  previewStudentImport,
  startSession,
  submitAnswers,
  transferStudent,
  updateClass,
  updateCourseDay,
  updateOrganizationSettings,
  updateSubject,
  updateTimeSlot,
  updateStudent,
} from './api'
import { setOrganizationId } from './api'
import { useAuth } from './App'
import type { AssessmentSession, ClassDetail, Classroom, CourseDay, ExamType, Organization, QuestionStats, Results, SchoolStage, Student, StudentImportItem, StudentImportPreview, Subject, Teacher, TimeSlot } from './types'

const options = ['A', 'B', 'C', 'D'] as const
const stageLabels: Record<SchoolStage, string> = { PRIMARY: '小学', MIDDLE: '初中', HIGH: '高中' }
const dayLabels: Record<number, string> = { 1: '周一', 2: '周二', 3: '周三', 4: '周四', 5: '周五', 6: '周六', 7: '周日' }
const examTypeLabels: Record<ExamType, string> = { ENTRY: '进门测', IN_CLASS: '随堂测', EXIT: '出门测', CUSTOM: '自定义测试' }

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
  const [password, setPassword] = useState('')
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
    <div className="login-panel"><div className="login-panel-inner"><div className="mobile-login-brand"><div className="brand-mark">答</div><strong>课堂答题台</strong></div><div className="login-heading"><span className="eyebrow">欢迎回来</span><h2>进入你的课堂工作台</h2><p>登录后管理班级、开始答题并查看实时反馈。</p></div><ErrorNotice message={error} /><form className="stack-form" onSubmit={handleSubmit}><label>邮箱地址<input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required /></label><label>密码<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label><button className="button button-primary button-full" disabled={submitting}>{submitting ? '正在进入…' : '进入工作台'}<span>→</span></button></form><div className="demo-hint"><span>演示环境</span><p>已填入演示教师账号，请输入测试密码登录。</p></div></div></div>
  </div>
}

function suggestedPrefixForWeb(name: string): string {
  const ascii = name.match(/[A-Za-z0-9]/g)?.join('').slice(0, 4).toUpperCase()
  if (ascii) return ascii
  return name.trim() === '叶芝' ? 'YZ' : 'ORG'
}

export function OrganizationSetupPage() {
  const { refreshProfile } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [prefix, setPrefix] = useState('')
  const [prefixTouched, setPrefixTouched] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleNameChange = (value: string) => {
    setName(value)
    if (!prefixTouched) setPrefix(suggestedPrefixForWeb(value))
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const organization = await createOrganization({ name: name.trim(), code_prefix: prefix.trim().toUpperCase(), organization_name: name.trim(), student_code_label: '学生编号' })
      setOrganizationId(organization.id)
      await refreshProfile()
      navigate('/dashboard', { replace: true })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '创建机构失败')
    } finally {
      setSubmitting(false)
    }
  }

  return <div className="onboarding-shell"><div className="onboarding-card"><div className="brand-mark brand-mark-large">答</div><span className="eyebrow">第一次使用</span><h1>先创建你的机构</h1><p>机构是学生主库、教师、班级和考试的共同边界。创建后，登录会直接进入这个工作台。</p><ErrorNotice message={error} /><form className="stack-form" onSubmit={handleSubmit}><label>机构名称<input value={name} onChange={(event) => handleNameChange(event.target.value)} placeholder="例如：叶芝" required /></label><label>机构代码前缀<input value={prefix} onChange={(event) => { setPrefixTouched(true); setPrefix(event.target.value.toUpperCase()) }} placeholder="例如：YZ" pattern="[A-Za-z0-9]{2,12}" required /><span className="form-hint">学生编号会由系统自动生成，例如 {prefix || 'YZ'}0001、{prefix || 'YZ'}0002；创建后不可用姓名代替。</span></label><button className="button button-primary button-full button-large" disabled={submitting}>{submitting ? '正在创建…' : '创建机构并进入工作台 →'}</button></form></div></div>
}

export function TeachersPage() {
  const [teachers, setTeachers] = useState<Teacher[]>([])
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ display_name: '', email: '', password: '' })
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const refresh = () => getTeachers().then(setTeachers).catch((caught) => setError(caught instanceof Error ? caught.message : '加载教师失败')).finally(() => setLoading(false))
  useEffect(() => { void refresh() }, [])
  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault(); setError(null); setMessage(null)
    try { await createTeacher(form); setForm({ display_name: '', email: '', password: '' }); setOpen(false); setMessage('教师账号已创建。'); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '创建教师失败') }
  }
  return <div className="page-stack"><PageHeading eyebrow="机构成员" title="教师管理" description="教师账号属于机构，班级只绑定教师关系，不改变学生的机构级编号。" action={<button className="button button-primary" onClick={() => setOpen((value) => !value)}>+ 新增教师</button>} /><ErrorNotice message={error} /><SuccessNotice message={message} />{open && <section className="panel form-panel"><div className="panel-heading"><div><span className="eyebrow">新教师</span><h2>创建教师登录账号</h2></div></div><form className="form-grid" onSubmit={handleSubmit}><label>教师姓名<input value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} placeholder="例如：王老师" required /></label><label>登录邮箱<input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} placeholder="teacher@example.com" required /></label><label>初始密码<input type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} minLength={1} required /></label><div className="form-actions"><button className="button button-primary">保存教师</button></div></form></section>}{loading ? <LoadingState /> : teachers.length ? <section className="panel"><div className="panel-heading"><div><span className="eyebrow">机构教师</span><h2>{teachers.length} 位教师</h2></div></div><div className="teacher-table"><div className="teacher-table-head"><span>教师</span><span>登录邮箱</span><span>负责班级</span><span>角色</span></div>{teachers.map((teacher) => <div className="teacher-table-row" key={teacher.id}><div className="student-identity"><span className="student-avatar">{teacher.display_name.slice(0, 1)}</span><strong>{teacher.display_name}</strong></div><span className="muted-copy">{teacher.email}</span><span>{teacher.class_count} 个班级</span><span className="role-pill">{teacher.role === 'TEACHER' ? '教师' : '管理员'}</span></div>)}</div></section> : <EmptyState title="还没有教师账号" description="创建教师后，新建班级时就可以指定授课教师。" />}</div>
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
    <PageHeading eyebrow="今天的考试" title={`早上好，${me?.display_name || '老师'}`} description="把注意力放回课堂，数据交给答题台。" action={<Link to="/sessions/new" className="button button-primary">+ 新建考试</Link>} />
    {activeSession && activeResults ? <section className="active-banner"><div className="active-banner-main"><div className="live-pulse"><span className="status-dot status-dot-live" />正在进行</div><h2>{activeSession.name || '未命名考试'}</h2><p>{activeSession.class_name} · {activeSession.question_count} 道题 · {formatDate(activeSession.started_at)}</p></div><div className="active-metrics"><div><strong>{activeResults.submitted_count}</strong><span>已提交</span></div><div><strong>{activeResults.pending_count}</strong><span>待提交</span></div><div><strong>{activeResults.average_correct_rate}%</strong><span>当前正确率</span></div><Link to={`/sessions/${activeSession.id}/live`} className="button button-light">进入考试 →</Link></div></section> : <section className="welcome-card"><div><span className="eyebrow">准备开始</span><h2>创建一场考试</h2><p>选一个班级，录入标准答案，几十秒即可开始。</p><Link to="/sessions/new" className="button button-primary">创建第一场考试</Link></div><div className="welcome-orbit"><span>答案</span><span>提交</span><span>反馈</span><div className="orbit-core">↗</div></div></section>}
    <section className="metric-grid"><MetricCard label="管理中的班级" value={classes.length} detail={`${classes.reduce((total, classroom) => total + classroom.student_count, 0)} 名学生`} icon="▦" /><MetricCard label="本月考试" value={sessions.filter((session) => session.created_at.slice(0, 7) === new Date().toISOString().slice(0, 7)).length} detail="持续累积考试数据" icon="◷" /><MetricCard label="最近考试" value={sessions.length ? formatDate(sessions[0].created_at) : '—'} detail={sessions[0]?.class_name || '还没有历史记录'} icon="⌁" /></section>
    <div className="dashboard-columns"><section className="panel"><div className="panel-heading"><div><span className="eyebrow">快捷入口</span><h2>从这里继续</h2></div></div><div className="shortcut-grid"><Link to="/classes" className="shortcut-card"><span className="shortcut-icon shortcut-teal">▦</span><strong>管理班级</strong><span>添加学生、调班或归档</span><b>→</b></Link><Link to="/students" className="shortcut-card"><span className="shortcut-icon shortcut-orange">◉</span><strong>学生名册</strong><span>搜索和维护学生资料</span><b>→</b></Link><Link to="/sessions" className="shortcut-card"><span className="shortcut-icon shortcut-blue">◷</span><strong>历史考试</strong><span>复盘每次答题表现</span><b>→</b></Link></div></section><section className="panel recent-panel"><div className="panel-heading"><div><span className="eyebrow">最近活动</span><h2>考试记录</h2></div><Link to="/sessions" className="quiet-link">查看全部 →</Link></div>{sessions.slice(0, 4).map((session) => <Link className="recent-row" to={`/sessions/${session.id}/${session.status === 'ACTIVE' ? 'live' : 'results'}`} key={session.id}><span className={`session-mini-mark session-mini-${session.status.toLowerCase()}`}>{session.status === 'ACTIVE' ? '●' : '✓'}</span><div><strong>{session.name || '未命名考试'}</strong><span>{session.class_name} · {formatDate(session.created_at)}</span></div><StatusBadge status={session.status} /></Link>)}{!sessions.length && <p className="muted-copy">还没有考试记录。</p>}</section></div>
  </div>
}

function MetricCard({ label, value, detail, icon }: { label: string; value: string | number; detail: string; icon: string }) {
  return <div className="metric-card"><span className="metric-icon">{icon}</span><span className="eyebrow">{label}</span><strong>{value}</strong><small>{detail}</small></div>
}

function StatusBadge({ status }: { status: string }) {
  const label: Record<string, string> = { ACTIVE: '进行中', DRAFT: '草稿', CLOSED: '已结束', ARCHIVED: '已归档', INACTIVE: '已归档', SUBMITTED: '已提交', REVIEW_REQUIRED: '待复核', PENDING: '未提交' }
  return <span className={`status-badge status-badge-${status.toLowerCase()}`}><span />{label[status] || status}</span>
}

export function OrganizationsPage() {
  const { me, refreshProfile } = useAuth()
  const organizations = me?.memberships.map((membership) => membership.organization) || []
  const [selectedId, setSelectedId] = useState(organizations[0]?.id || '')
  const selected = organizations.find((organization) => organization.id === selectedId) || organizations[0]
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState({ name: '', code_prefix: '', organization_name: '', student_code_label: '学生编号' })
  const [settingsForm, setSettingsForm] = useState({ code_prefix: '', organization_name: '', student_code_label: '学生编号' })
  const [subjects, setSubjects] = useState<Subject[]>([])
  const [timeSlots, setTimeSlots] = useState<TimeSlot[]>([])
  const [courseDays, setCourseDays] = useState<CourseDay[]>([])
  const [subjectName, setSubjectName] = useState('')
  const [dayForm, setDayForm] = useState({ weekday: '1', display_name: '周一' })
  const [slotForm, setSlotForm] = useState({ slot_code: 'E', display_name: '晚间段', start_time: '18:40', end_time: '20:50', applicable_school_stage: 'MIDDLE' as SchoolStage | '' })
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refreshCatalog = async () => {
    if (!selected) return
    setCatalogLoading(true)
    try {
      const [loadedSubjects, loadedSlots, loadedDays] = await Promise.all([getSubjects(true), getTimeSlots(true), getCourseDays()])
      setSubjects(loadedSubjects)
      setTimeSlots(loadedSlots)
      setCourseDays(loadedDays)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '加载机构配置失败')
    } finally {
      setCatalogLoading(false)
    }
  }

  useEffect(() => {
    if (!selected) return
    setSettingsForm({ code_prefix: selected.code_prefix, organization_name: selected.settings?.organization_name || selected.name, student_code_label: selected.settings?.student_code_label || '学生编号' })
    void refreshCatalog()
  }, [selected?.id])

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault(); setError(null); setMessage(null)
    try {
      const organization = await createOrganization({ name: form.name, code_prefix: form.code_prefix || undefined, organization_name: form.organization_name || form.name, student_code_label: form.student_code_label })
      setOrganizationId(organization.id); setSelectedId(organization.id); setForm({ name: '', code_prefix: '', organization_name: '', student_code_label: '学生编号' }); setCreateOpen(false); await refreshProfile(); setMessage('机构已创建，已切换到新机构。')
    } catch (caught) { setError(caught instanceof Error ? caught.message : '创建机构失败') }
  }

  const handleSettings = async (event: FormEvent) => {
    event.preventDefault(); if (!selected) return; setError(null); setMessage(null)
    try { await updateOrganizationSettings(selected.id, { code_prefix: settingsForm.code_prefix, organization_name: settingsForm.organization_name, student_code_label: settingsForm.student_code_label }); await refreshProfile(); setMessage('机构配置已保存。') } catch (caught) { setError(caught instanceof Error ? caught.message : '保存失败') }
  }

  const handleCreateSubject = async (event: FormEvent) => {
    event.preventDefault(); if (!subjectName.trim()) return
    try { await createSubject({ name: subjectName.trim() }); setSubjectName(''); setMessage('科目已添加。'); await refreshCatalog() } catch (caught) { setError(caught instanceof Error ? caught.message : '添加科目失败') }
  }

  const handleToggleSubject = async (subject: Subject) => {
    try { await updateSubject(subject.id, { active: !subject.active }); setMessage(`科目已${subject.active ? '停用' : '启用'}。`); await refreshCatalog() } catch (caught) { setError(caught instanceof Error ? caught.message : '更新科目失败') }
  }

  const handleCreateDay = async (event: FormEvent) => {
    event.preventDefault()
    try { await createCourseDay({ weekday: Number(dayForm.weekday), display_name: dayForm.display_name.trim() }); setMessage('上课日已添加。'); await refreshCatalog() } catch (caught) { setError(caught instanceof Error ? caught.message : '添加上课日失败') }
  }

  const handleToggleDay = async (day: CourseDay) => {
    try { await updateCourseDay(day.weekday, { status: day.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' }); setMessage(`上课日已${day.status === 'ACTIVE' ? '关闭' : '启用'}。`); await refreshCatalog() } catch (caught) { setError(caught instanceof Error ? caught.message : '更新上课日失败') }
  }

  const handleCreateSlot = async (event: FormEvent) => {
    event.preventDefault()
    try { await createTimeSlot({ ...slotForm, applicable_school_stage: slotForm.applicable_school_stage || null }); setMessage('上课时段已添加。'); await refreshCatalog() } catch (caught) { setError(caught instanceof Error ? caught.message : '添加时段失败') }
  }

  const handleToggleSlot = async (slot: TimeSlot) => {
    try { await updateTimeSlot(slot.id, { active: !slot.active }); setMessage(`时段已${slot.active ? '停用' : '启用'}。`); await refreshCatalog() } catch (caught) { setError(caught instanceof Error ? caught.message : '更新时段失败') }
  }

  return <div className="page-stack"><PageHeading eyebrow="组织与品牌" title="系统设置" description="机构代码、学生编号、学科、上课日和时段都在机构边界内维护。" action={<button className="button button-primary" onClick={() => setCreateOpen((value) => !value)}>+ 新建机构</button>} /><ErrorNotice message={error} /><SuccessNotice message={message} />{createOpen && <section className="panel form-panel"><div className="panel-heading"><div><span className="eyebrow">新机构</span><h2>创建一个新的课堂空间</h2></div></div><form className="form-grid" onSubmit={handleCreate}><label>机构名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：叶芝" required /></label><label>机构代码前缀<input value={form.code_prefix} onChange={(event) => setForm({ ...form, code_prefix: event.target.value.toUpperCase() })} placeholder="例如：YZ" pattern="[A-Za-z0-9]{2,12}" required /></label><label>展示名称（可选）<input value={form.organization_name} onChange={(event) => setForm({ ...form, organization_name: event.target.value })} placeholder="默认使用机构名称" /></label><label>学生编号标签<input value={form.student_code_label} onChange={(event) => setForm({ ...form, student_code_label: event.target.value })} required /></label><div className="form-actions"><button className="button button-primary">创建机构</button><button type="button" className="button button-ghost" onClick={() => setCreateOpen(false)}>取消</button></div></form></section>}<div className="two-column-layout"><section className="panel"><div className="panel-heading"><div><span className="eyebrow">我的机构</span><h2>选择工作空间</h2></div></div><div className="org-list">{organizations.map((organization) => <button className={`org-list-item ${selected?.id === organization.id ? 'org-list-item-active' : ''}`} key={organization.id} onClick={() => { setSelectedId(organization.id); setOrganizationId(organization.id) }}><span className="org-avatar">{organization.name.slice(0, 1)}</span><span><strong>{organization.name}</strong><small>{organization.code_prefix} · 下一个 {organization.code_prefix}{String(organization.student_serial + 1).padStart(4, '0')}</small></span><span className="org-chevron">→</span></button>)}</div></section>{selected && <section className="panel"><div className="panel-heading"><div><span className="eyebrow">当前机构</span><h2>{selected.name}</h2></div><StatusBadge status={selected.status} /></div><form className="stack-form" onSubmit={handleSettings}><label>机构代码前缀<input value={settingsForm.code_prefix} onChange={(event) => setSettingsForm({ ...settingsForm, code_prefix: event.target.value.toUpperCase() })} pattern="[A-Za-z0-9]{2,12}" required /></label><label>机构展示名称<input value={settingsForm.organization_name} onChange={(event) => setSettingsForm({ ...settingsForm, organization_name: event.target.value })} required /></label><label>学生编号标签<input value={settingsForm.student_code_label} onChange={(event) => setSettingsForm({ ...settingsForm, student_code_label: event.target.value })} required /></label><div className="settings-tip"><span>i</span>学生编号由后端机构流水号生成，创建后永久不变；已有学生后不能更换机构前缀。</div><button className="button button-primary">保存配置</button></form></section>}</div>{selected && <section className="panel settings-catalog-panel"><div className="panel-heading"><div><span className="eyebrow">机构配置</span><h2>学科、上课日与时段</h2></div>{catalogLoading && <span className="muted-copy">正在同步…</span>}</div><div className="settings-catalog-grid"><div className="settings-catalog-card"><div className="settings-card-heading"><h3>学科</h3><span>{subjects.filter((subject) => subject.active).length} 个启用</span></div><div className="settings-chip-list">{subjects.map((subject) => <button type="button" className={`settings-chip ${subject.active ? '' : 'settings-chip-inactive'}`} key={subject.id} onClick={() => handleToggleSubject(subject)}>{subject.name}<small>{subject.active ? '启用' : '停用'}</small></button>)}</div><form className="settings-inline-form" onSubmit={handleCreateSubject}><input value={subjectName} onChange={(event) => setSubjectName(event.target.value)} placeholder="新增科目，例如：生物" /><button className="button button-secondary">添加</button></form></div><div className="settings-catalog-card"><div className="settings-card-heading"><h3>上课日</h3><span>关闭不会删除历史班级</span></div><div className="settings-row-list">{courseDays.map((day) => <div className="settings-row" key={day.id}><span><strong>{day.display_name}</strong><small>星期 {day.weekday}</small></span><button type="button" className={`status-toggle ${day.status === 'ACTIVE' ? 'status-toggle-active' : ''}`} onClick={() => handleToggleDay(day)}>{day.status === 'ACTIVE' ? '启用' : '已关闭'}</button></div>)}</div><form className="settings-inline-form" onSubmit={handleCreateDay}><select value={dayForm.weekday} onChange={(event) => setDayForm({ ...dayForm, weekday: event.target.value })}>{Object.entries(dayLabels).map(([weekday, label]) => <option value={weekday} key={weekday}>{label}</option>)}</select><input value={dayForm.display_name} onChange={(event) => setDayForm({ ...dayForm, display_name: event.target.value })} placeholder="显示名称" /><button className="button button-secondary">添加</button></form></div><div className="settings-catalog-card settings-slot-card"><div className="settings-card-heading"><h3>上课时段</h3><span>可按学段限制</span></div><div className="settings-row-list">{timeSlots.map((slot) => <div className="settings-row" key={slot.id}><span><strong>{slot.display_name}</strong><small>{slot.slot_code} · {slot.start_time} - {slot.end_time} · {slot.applicable_school_stage ? stageLabels[slot.applicable_school_stage] : '全部学段'}</small></span><button type="button" className={`status-toggle ${slot.active ? 'status-toggle-active' : ''}`} onClick={() => handleToggleSlot(slot)}>{slot.active ? '启用' : '已停用'}</button></div>)}</div><form className="settings-slot-form" onSubmit={handleCreateSlot}><div className="form-grid"><label>编码<input value={slotForm.slot_code} onChange={(event) => setSlotForm({ ...slotForm, slot_code: event.target.value.toUpperCase() })} required /></label><label>名称<input value={slotForm.display_name} onChange={(event) => setSlotForm({ ...slotForm, display_name: event.target.value })} required /></label><label>开始<input type="time" value={slotForm.start_time} onChange={(event) => setSlotForm({ ...slotForm, start_time: event.target.value })} required /></label><label>结束<input type="time" value={slotForm.end_time} onChange={(event) => setSlotForm({ ...slotForm, end_time: event.target.value })} required /></label><label>适用学段<select value={slotForm.applicable_school_stage} onChange={(event) => setSlotForm({ ...slotForm, applicable_school_stage: event.target.value as SchoolStage | '' })}><option value="">全部学段</option><option value="PRIMARY">小学</option><option value="MIDDLE">初中</option><option value="HIGH">高中</option></select></label><div className="form-actions"><button className="button button-secondary">添加时段</button></div></div></form></div></div></section>}</div>
}

export function ClassesPage() {
  const [classes, setClasses] = useState<Classroom[]>([])
  const [teachers, setTeachers] = useState<Teacher[]>([])
  const [days, setDays] = useState<CourseDay[]>([])
  const [timeSlots, setTimeSlots] = useState<TimeSlot[]>([])
  const [form, setForm] = useState({ name: '', teacher_id: '', school_stage: 'MIDDLE' as SchoolStage, grade: '', day_of_week: '6', time_slot_id: '' })
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const refresh = () => getClasses().then(setClasses).catch((caught) => setError(caught instanceof Error ? caught.message : '加载班级失败')).finally(() => setLoading(false))
  useEffect(() => { void refresh(); Promise.all([getTeachers(), getCourseDays(), getTimeSlots()]).then(([loadedTeachers, loadedDays, loadedSlots]) => { setTeachers(loadedTeachers); setDays(loadedDays.filter((day) => day.status === 'ACTIVE')); setTimeSlots(loadedSlots) }).catch((caught) => setError(caught instanceof Error ? caught.message : '加载班级配置失败')) }, [])
  const selectedSlot = timeSlots.find((slot) => slot.id === form.time_slot_id)
  const availableSlots = timeSlots.filter((slot) => !slot.applicable_school_stage || slot.applicable_school_stage === form.school_stage)
  const suggestedName = `${teachers.find((teacher) => teacher.id === form.teacher_id)?.display_name || '授课教师'} · ${stageLabels[form.school_stage]} · ${dayLabels[Number(form.day_of_week)] || '上课日'} · ${selectedSlot?.display_name || '时段'}`
  const handleCreate = async (event: FormEvent) => { event.preventDefault(); setError(null); setMessage(null); try { await createClass({ name: form.name.trim() || suggestedName, teacher_id: form.teacher_id || null, school_stage: form.school_stage, grade: form.grade.trim() || null, day_of_week: form.day_of_week ? Number(form.day_of_week) : null, time_slot_id: form.time_slot_id || null }); setForm({ ...form, name: '' }); setOpen(false); setMessage('班级已创建。'); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '创建班级失败') } }
  return <div className="page-stack"><PageHeading eyebrow="组织结构" title="班级管理" description="班级是教师与学生在一段时间内的学习关系，学生编号不会因调班改变。" action={<div className="button-row"><Link to="/sessions/new" className="button button-secondary">+ 新建考试</Link><button className="button button-primary" onClick={() => setOpen((value) => !value)}>+ 新建班级</button></div>} /><ErrorNotice message={error} /><SuccessNotice message={message} />{open && <section className="panel form-panel class-create-panel"><div className="panel-heading"><div><span className="eyebrow">新建班级</span><h2>设置授课关系与上课安排</h2></div></div><form className="form-grid" onSubmit={handleCreate}><label>授课教师<select value={form.teacher_id} onChange={(event) => setForm({ ...form, teacher_id: event.target.value })} required><option value="">请选择教师</option>{teachers.map((teacher) => <option value={teacher.id} key={teacher.id}>{teacher.display_name} · {teacher.role === 'TEACHER' ? '教师' : '管理员'}</option>)}</select></label><label>学段<select value={form.school_stage} onChange={(event) => { const next = event.target.value as SchoolStage; setForm({ ...form, school_stage: next, time_slot_id: '' }) }}><option value="PRIMARY">小学</option><option value="MIDDLE">初中</option><option value="HIGH">高中</option></select></label><label>上课日<select value={form.day_of_week} onChange={(event) => setForm({ ...form, day_of_week: event.target.value })} required><option value="">请选择上课日</option>{days.map((day) => <option value={day.weekday} key={day.id}>{day.display_name}</option>)}</select></label><label>上课时段<select value={form.time_slot_id} onChange={(event) => setForm({ ...form, time_slot_id: event.target.value })} required><option value="">请选择时段</option>{availableSlots.map((slot) => <option value={slot.id} key={slot.id}>{slot.display_name} · {slot.start_time} - {slot.end_time}</option>)}</select></label><label>年级 <span className="optional">可选</span><input value={form.grade} onChange={(event) => setForm({ ...form, grade: event.target.value })} placeholder="例如：初二" /></label><label>班级名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder={suggestedName} required /></label><p className="form-hint wide-label">建议名称：{suggestedName}。你可以直接修改名称；班级 ID 由数据库生成。</p><div className="form-actions"><button className="button button-primary">保存班级</button><button type="button" className="button button-ghost" onClick={() => setOpen(false)}>取消</button></div></form></section>}{loading ? <LoadingState /> : classes.length ? <div className="class-grid">{classes.map((classroom) => <article className={`class-card ${classroom.status === 'ARCHIVED' ? 'class-card-archived' : ''}`} key={classroom.id}><div className="class-card-top"><span className="class-symbol">{classroom.name.slice(0, 1)}</span><StatusBadge status={classroom.status} /></div><h2>{classroom.name}</h2><p className="class-meta">{classroom.teacher_name || '未指定教师'} · {stageLabels[classroom.school_stage]} · {classroom.day_of_week ? dayLabels[classroom.day_of_week] : '未排课'}{classroom.time_slot_name ? ` · ${classroom.time_slot_name}` : ''}</p><p><strong>{classroom.student_count}</strong> 名在班学生</p><div className="class-card-actions"><Link to={`/classes/${classroom.id}`} className="button button-secondary">查看班级</Link>{classroom.status === 'ACTIVE' && <Link to={`/sessions/new?classId=${classroom.id}`} className="button button-quiet">新建考试 →</Link>}</div></article>)}</div> : <EmptyState title="还没有班级" description="创建第一个班级，然后从机构学生库批量添加。" />}</div>
}

export function ClassDetailPage() {
  const { classId } = useParams<{ classId: string }>()
  const [detail, setDetail] = useState<ClassDetail | null>(null)
  const [allStudents, setAllStudents] = useState<Student[]>([])
  const [classes, setClasses] = useState<Classroom[]>([])
  const [search, setSearch] = useState('')
  const [addOpen, setAddOpen] = useState(false)
  const [mode, setMode] = useState<'new' | 'existing' | 'import'>('existing')
  const [newStudent, setNewStudent] = useState({ name: '', school_stage: 'PRIMARY' as SchoolStage })
  const [selectedStudentIds, setSelectedStudentIds] = useState<string[]>([])
  const [importPreview, setImportPreview] = useState<StudentImportPreview | null>(null)
  const [importActions, setImportActions] = useState<Record<number, { action: string; student_id?: string }>>({})
  const [className, setClassName] = useState('')
  const [transferId, setTransferId] = useState('')
  const [transferTarget, setTransferTarget] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const refresh = () => { if (classId) getClass(classId).then((value) => { setDetail(value); setClassName(value.name) }).catch((caught) => setError(caught instanceof Error ? caught.message : '加载班级失败')) }
  useEffect(() => { refresh(); getClasses().then(setClasses).catch(() => undefined) }, [classId])
  const filteredStudents = detail?.students.filter((student) => `${student.name}${student.student_code}`.toLowerCase().includes(search.toLowerCase())) || []
  const loadAllStudents = () => getStudents().then(setAllStudents).catch((caught) => setError(caught instanceof Error ? caught.message : '加载学生失败'))
  const openAdd = (nextMode: 'new' | 'existing' | 'import') => { setMode(nextMode); setAddOpen(true); setError(null); setMessage(null); if (nextMode === 'existing') { setSelectedStudentIds([]); loadAllStudents() } }
  const handleNew = async (event: FormEvent) => { event.preventDefault(); if (!classId) return; setError(null); try { const student = await createStudent(newStudent); await addStudentToClass(classId, student.id, false); setNewStudent({ name: '', school_stage: 'PRIMARY' }); setAddOpen(false); setMessage(`学生已创建并加入班级，编号为 ${student.student_code}。`); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '添加学生失败') } }
  const handleExisting = async (event: FormEvent) => { event.preventDefault(); if (!classId || !selectedStudentIds.length) return; setError(null); try { await bulkAttachStudents(classId, selectedStudentIds); setSelectedStudentIds([]); setAddOpen(false); setMessage(`已从机构学生库加入 ${selectedStudentIds.length} 名学生。`); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '加入班级失败') } }
  const handleImportFile = async (event: React.ChangeEvent<HTMLInputElement>) => { const file = event.target.files?.[0]; if (!file) return; setError(null); setMessage(null); try { const preview = await previewStudentImport(file); setImportPreview(preview); setImportActions(Object.fromEntries(preview.items.map((item) => [item.row_number, { action: item.default_action, student_id: item.matches[0]?.id }]))) } catch (caught) { setError(caught instanceof Error ? caught.message : '解析 Excel 失败') } }
  const handleImportConfirm = async () => { if (!classId || !importPreview) return; const items = importPreview.items.filter((item) => item.status !== 'EMPTY_NAME' && item.status !== 'INVALID_STAGE').map((item) => { const choice = importActions[item.row_number] || { action: item.default_action, student_id: item.matches[0]?.id }; return { row_number: item.row_number, name: item.name, school_stage: item.school_stage || 'PRIMARY', remark: item.remark, action: choice.action, student_id: choice.student_id } }); setError(null); try { const result = await confirmStudentImport({ class_id: classId, items }); setImportPreview(null); setAddOpen(false); setMessage(`导入完成：新增 ${result.created_count} 名，复用 ${result.reused_count} 名，加入班级 ${result.membership_added_count} 名。`); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '确认导入失败') } }
  const handleRemove = async (student: Student) => { if (!classId || !window.confirm(`确认将 ${student.name} 移出 ${detail?.name}？学生资料和历史成绩会保留。`)) return; try { await removeStudentFromClass(classId, student.id); setMessage(`${student.name} 已移出班级，历史记录保留。`); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '移出失败') } }
  const handleTransfer = async () => { if (!transferId || !classId || !transferTarget) return; try { await transferStudent(transferId, transferTarget, classId); setMessage('学生已转入新班级，学生编号和历史记录保持不变。'); setTransferId(''); setTransferTarget(''); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '转班失败') } }
  const handleRename = async (event: FormEvent) => { event.preventDefault(); if (!classId || !className.trim() || className === detail?.name) return; try { await updateClass(classId, { name: className.trim() }); setMessage('班级名称已更新。'); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '保存班级失败') } }
  if (!detail) return <LoadingState />
  const selectableStudents = allStudents.filter((student) => student.status === 'ACTIVE' && !detail.students.some((current) => current.id === student.id) && `${student.name}${student.student_code}`.toLowerCase().includes(search.toLowerCase()))
  return <div className="page-stack"><PageHeading eyebrow="班级详情" title={detail.name} description={`${detail.student_count} 名在班学生 · ${detail.teacher_name || '未指定教师'} · ${stageLabels[detail.school_stage]} · ${detail.day_of_week ? dayLabels[detail.day_of_week] : '未排课'}${detail.time_slot_name ? ` · ${detail.time_slot_name}` : ''}`} action={<div className="button-row"><Link to={`/sessions/new?classId=${detail.id}`} className="button button-primary">+ 新建考试</Link><button className="button button-secondary" onClick={() => openAdd('existing')}>+ 添加学生</button></div>} /><ErrorNotice message={error} /><SuccessNotice message={message} /><section className="panel class-toolbar"><form onSubmit={handleRename} className="rename-form"><label>班级名称<input value={className} onChange={(event) => setClassName(event.target.value)} /></label><button className="button button-quiet" disabled={className === detail.name}>保存</button></form><div className="student-tools"><label className="search-field"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索姓名或学生编号" /></label><div className="button-row"><button className="button button-quiet" onClick={() => openAdd('import')}>Excel 导入</button><button className="button button-quiet" onClick={() => exportClass(detail.id).catch((caught) => setError(caught instanceof Error ? caught.message : '导出失败'))}>导出名单</button></div></div></section>{addOpen && <section className="panel add-student-panel"><div className="panel-heading"><div><span className="eyebrow">机构学生库 → 班级关系</span><h2>添加学生</h2></div><button className="icon-button" onClick={() => setAddOpen(false)} aria-label="关闭">×</button></div><div className="segmented-control"><button type="button" className={mode === 'existing' ? 'selected' : ''} onClick={() => { setMode('existing'); loadAllStudents() }}>从机构学生库选择</button><button type="button" className={mode === 'import' ? 'selected' : ''} onClick={() => setMode('import')}>Excel 批量导入</button><button type="button" className={mode === 'new' ? 'selected' : ''} onClick={() => setMode('new')}>新增单个学生</button></div>{mode === 'existing' && <form className="stack-form" onSubmit={handleExisting}><div className="selection-toolbar"><span>已选 {selectedStudentIds.length} 人</span><button type="button" className="text-button" onClick={() => setSelectedStudentIds(selectableStudents.map((student) => student.id))}>全选当前结果</button></div><div className="student-select-list">{selectableStudents.length ? selectableStudents.map((student) => <label className="student-select-row" key={student.id}><input type="checkbox" checked={selectedStudentIds.includes(student.id)} onChange={(event) => setSelectedStudentIds((current) => event.target.checked ? [...current, student.id] : current.filter((id) => id !== student.id))} /><span className="student-avatar">{student.name.slice(0, 1)}</span><span><strong>{student.name}</strong><small>{student.student_code} · {stageLabels[student.school_stage]}</small></span></label>) : <p className="muted-copy">没有可加入的机构学生，请先在学生库新增或导入。</p>}</div><p className="form-hint">此入口允许一个学生加入多个班级；需要结束原班级关系时，请在成员列表使用“转班”。</p><button className="button button-primary" disabled={!selectedStudentIds.length}>批量加入当前班级</button></form>}{mode === 'import' && <div className="stack-form"><div className="button-row import-template-row"><button type="button" className="button button-quiet" onClick={() => exportStudentImportTemplate().catch((caught) => setError(caught instanceof Error ? caught.message : '下载模板失败'))}>下载模板</button><label className="button button-secondary file-button">选择 Excel / CSV<input type="file" accept=".xlsx,.xlsm,.csv" onChange={handleImportFile} /></label></div><p className="form-hint">最低只需要一列“姓名”，可选“学段”“备注”。上传后先匹配预览，确认后才写入机构学生库和本班关系。</p>{importPreview && <div className="import-preview"><div className="import-summary"><span>总人数 <b>{importPreview.total_rows}</b></span><span>已有学生 <b>{importPreview.existing_count}</b></span><span>准备新增 <b>{importPreview.prepare_create_count}</b></span><span>待确认/异常 <b>{importPreview.duplicate_count + importPreview.error_count}</b></span></div><div className="import-item-list">{importPreview.items.map((item: StudentImportItem) => { const choice = importActions[item.row_number] || { action: item.default_action, student_id: item.matches[0]?.id }; return <div className={`import-item import-item-${item.status.toLowerCase()}`} key={item.row_number}><div><strong>第 {item.row_number} 行 · {item.name || '未填写姓名'}</strong><small>{item.error || (item.matches.length ? `找到 ${item.matches.length} 个同名学生` : '机构库中未找到')}</small></div><div className="import-item-controls"><select value={choice.action} onChange={(event) => setImportActions((current) => ({ ...current, [item.row_number]: { ...choice, action: event.target.value } }))}><option value="USE_EXISTING">使用已有学生</option><option value="CREATE">新建同名学生</option><option value="SKIP">跳过</option></select>{choice.action === 'USE_EXISTING' && item.matches.length > 0 && <select value={choice.student_id || ''} onChange={(event) => setImportActions((current) => ({ ...current, [item.row_number]: { ...choice, student_id: event.target.value } }))}>{item.matches.map((match) => <option value={match.id} key={match.id}>{match.student_code} · {match.name}{match.current_classes.length ? ` · ${match.current_classes.join('、')}` : ''}</option>)}</select>}</div></div> })}</div><button className="button button-primary" onClick={handleImportConfirm} disabled={importPreview.error_count === importPreview.total_rows}>确认导入并加入班级</button></div>}</div>}{mode === 'new' && <form className="form-grid" onSubmit={handleNew}><label>姓名<input value={newStudent.name} onChange={(event) => setNewStudent({ ...newStudent, name: event.target.value })} placeholder="例如：张三" required /></label><label>学段<select value={newStudent.school_stage} onChange={(event) => setNewStudent({ ...newStudent, school_stage: event.target.value as SchoolStage })}><option value="PRIMARY">小学</option><option value="MIDDLE">初中</option><option value="HIGH">高中</option></select></label><p className="form-hint wide-label">学生编号由机构统一流水号自动生成，当前学生创建后不会因调班改变。</p><div className="form-actions"><button className="button button-primary">创建并加入</button></div></form>}</section>}<section className="panel"><div className="panel-heading"><div><span className="eyebrow">当前成员</span><h2>{filteredStudents.length} 名学生</h2></div><span className="muted-copy">移出只解除 ClassMembership，不删除机构学生</span></div>{filteredStudents.length ? <div className="student-table"><div className="student-table-head"><span>学生</span><span>编号</span><span>状态</span><span>关系操作</span></div>{filteredStudents.map((student) => <div className="student-table-row" key={student.id}><div className="student-identity"><span className="student-avatar">{student.name.slice(0, 1)}</span><div><strong>{student.name}</strong><small>{stageLabels[student.school_stage]}</small></div></div><span className="student-code">{student.student_code}</span><StatusBadge status={student.status} /><div className="row-actions"><button className="row-action" onClick={() => { setTransferId(student.id); setTransferTarget('') }}>转班</button><button className="row-action" onClick={() => handleRemove(student)}>移出</button></div>{transferId === student.id && <div className="transfer-inline"><select value={transferTarget} onChange={(event) => setTransferTarget(event.target.value)}><option value="">选择目标班级</option>{classes.filter((classroom) => classroom.id !== classId && classroom.status === 'ACTIVE').map((classroom) => <option key={classroom.id} value={classroom.id}>{classroom.name}</option>)}</select><button className="button button-primary" onClick={handleTransfer} disabled={!transferTarget}>确认转班</button><button className="button button-ghost" onClick={() => setTransferId('')}>取消</button></div>}</div>)}</div> : <EmptyState title={search ? '没有匹配学生' : '班级还没有学生'} description={search ? '换个姓名或学生编号试试。' : '从机构学生库批量选择或导入第一批学生。'} action={!search ? <button className="button button-secondary" onClick={() => openAdd('existing')}>选择学生</button> : undefined} />}</section></div>
}

export function StudentsPage() {
  const { me } = useAuth()
  const [students, setStudents] = useState<Student[]>([])
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: '', school_stage: 'PRIMARY' as SchoolStage, remark: '' })
  const [importPreview, setImportPreview] = useState<StudentImportPreview | null>(null)
  const [importActions, setImportActions] = useState<Record<number, { action: string; student_id?: string }>>({})
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const currentMembership = me?.memberships.find((membership) => membership.organization_id === getOrganizationId()) || me?.memberships[0]
  const canArchive = currentMembership?.role === 'OWNER' || currentMembership?.role === 'ADMIN'
  const refresh = () => getStudents(search).then(setStudents).catch((caught) => setError(caught instanceof Error ? caught.message : '加载学生失败'))
  useEffect(() => { void refresh() }, [search])
  const handleCreate = async (event: FormEvent) => { event.preventDefault(); setError(null); try { const student = await createStudent(form); setForm({ name: '', school_stage: 'PRIMARY', remark: '' }); setOpen(false); setMessage(`学生已创建，机构编号为 ${student.student_code}。`); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '创建学生失败') } }
  const handleToggleArchive = async (student: Student) => {
    if (!canArchive) return
    const nextStatus = student.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE'
    if (!window.confirm(`${nextStatus === 'INACTIVE' ? '归档' : '恢复'} ${student.name}？历史考试、成绩和扫描记录会保留。`)) return
    setError(null)
    try { await updateStudent(student.id, { status: nextStatus }); setMessage(`${student.name} 已${nextStatus === 'INACTIVE' ? '归档' : '恢复'}。`); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '更新学生状态失败') }
  }
  const handleImportFile = async (event: React.ChangeEvent<HTMLInputElement>) => { const file = event.target.files?.[0]; if (!file) return; setError(null); try { const preview = await previewStudentImport(file); setImportPreview(preview); setImportActions(Object.fromEntries(preview.items.map((item) => [item.row_number, { action: item.default_action, student_id: item.matches[0]?.id }]))) } catch (caught) { setError(caught instanceof Error ? caught.message : '解析 Excel 失败') } }
  const handleImportConfirm = async () => { if (!importPreview) return; const items = importPreview.items.filter((item) => item.status !== 'EMPTY_NAME' && item.status !== 'INVALID_STAGE').map((item) => { const choice = importActions[item.row_number] || { action: item.default_action, student_id: item.matches[0]?.id }; return { row_number: item.row_number, name: item.name, school_stage: item.school_stage || 'PRIMARY', remark: item.remark, action: choice.action, student_id: choice.student_id } }); try { const result = await confirmStudentImport({ items }); setImportPreview(null); setMessage(`导入完成：新增 ${result.created_count} 名，复用 ${result.reused_count} 名，跳过 ${result.skipped_count} 行。`); refresh() } catch (caught) { setError(caught instanceof Error ? caught.message : '确认导入失败') } }
  return <div className="page-stack"><PageHeading eyebrow="机构主库" title="学生库" description="学生先属于机构，再通过 ClassMembership 加入班级。编号由机构流水号生成，换班也不会改变。" action={<div className="button-row"><button className="button button-secondary" onClick={() => exportStudents().catch((caught) => setError(caught instanceof Error ? caught.message : '导出失败'))}>导出学生库</button><button className="button button-primary" onClick={() => setOpen((value) => !value)}>+ 新增学生</button></div>} /><ErrorNotice message={error} /><SuccessNotice message={message} />{open && <section className="panel form-panel"><div className="panel-heading"><div><span className="eyebrow">单个学生</span><h2>建立机构学生资料</h2></div></div><form className="form-grid" onSubmit={handleCreate}><label>姓名<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：张三" required /></label><label>学段<select value={form.school_stage} onChange={(event) => setForm({ ...form, school_stage: event.target.value as SchoolStage })}><option value="PRIMARY">小学</option><option value="MIDDLE">初中</option><option value="HIGH">高中</option></select></label><label className="wide-label">备注 <span className="optional">可选</span><input value={form.remark} onChange={(event) => setForm({ ...form, remark: event.target.value })} placeholder="可留空" /></label><p className="form-hint wide-label">不要填写学生编号；系统会自动分配并保证机构内唯一。</p><div className="form-actions"><button className="button button-primary">保存学生</button></div></form></section>}<section className="panel import-library-panel"><div className="panel-heading"><div><span className="eyebrow">批量导入</span><h2>Excel 名单 → 学生主库</h2></div><div className="button-row"><button type="button" className="button button-quiet" onClick={() => exportStudentImportTemplate().catch((caught) => setError(caught instanceof Error ? caught.message : '下载模板失败'))}>下载模板</button><label className="button button-secondary file-button">选择 Excel / CSV<input type="file" accept=".xlsx,.xlsm,.csv" onChange={handleImportFile} /></label></div></div><p className="form-hint">模板最低只需要一列“姓名”，可选“学段”“备注”。系统会先匹配，再由你确认是否复用或创建同名学生。</p>{importPreview && <div className="import-preview"><div className="import-summary"><span>总人数 <b>{importPreview.total_rows}</b></span><span>已有学生 <b>{importPreview.existing_count}</b></span><span>准备新增 <b>{importPreview.prepare_create_count}</b></span><span>待确认/异常 <b>{importPreview.duplicate_count + importPreview.error_count}</b></span></div><div className="import-item-list">{importPreview.items.map((item: StudentImportItem) => { const choice = importActions[item.row_number] || { action: item.default_action, student_id: item.matches[0]?.id }; return <div className={`import-item import-item-${item.status.toLowerCase()}`} key={item.row_number}><div><strong>第 {item.row_number} 行 · {item.name || '未填写姓名'}</strong><small>{item.error || (item.matches.length ? `找到 ${item.matches.length} 个同名学生` : '机构库中未找到')}</small></div><div className="import-item-controls"><select value={choice.action} onChange={(event) => setImportActions((current) => ({ ...current, [item.row_number]: { ...choice, action: event.target.value } }))}><option value="USE_EXISTING">使用已有学生</option><option value="CREATE">新建同名学生</option><option value="SKIP">跳过</option></select>{choice.action === 'USE_EXISTING' && item.matches.length > 0 && <select value={choice.student_id || ''} onChange={(event) => setImportActions((current) => ({ ...current, [item.row_number]: { ...choice, student_id: event.target.value } }))}>{item.matches.map((match) => <option value={match.id} key={match.id}>{match.student_code} · {match.name}{match.current_classes.length ? ` · ${match.current_classes.join('、')}` : ''}</option>)}</select>}</div></div> })}</div><button className="button button-primary" onClick={handleImportConfirm} disabled={importPreview.error_count === importPreview.total_rows}>确认导入</button></div>}</section><section className="panel"><div className="panel-heading"><div><span className="eyebrow">学生主库</span><h2>{students.length} 名学生</h2></div><label className="search-field search-field-wide"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索姓名或学生编号" /></label></div>{students.length ? <div className="student-table"><div className="student-table-head"><span>学生</span><span>编号</span><span>学段</span><span>状态 / 操作</span></div>{students.map((student) => <div className="student-table-row" key={student.id}><div className="student-identity"><span className="student-avatar">{student.name.slice(0, 1)}</span><div><strong>{student.name}</strong><small>{student.remark || '机构学生'}</small></div></div><span className="student-code">{student.student_code}</span><span>{stageLabels[student.school_stage]}</span><div className="student-row-status"><StatusBadge status={student.status} />{canArchive && <button type="button" className="row-action" onClick={() => handleToggleArchive(student)}>{student.status === 'ACTIVE' ? '归档' : '恢复'}</button>}</div></div>)}</div> : <EmptyState title="没有找到学生" description="可以新增学生、导入名单或调整搜索条件。" />}</section></div>
}

export function NewSessionPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [classes, setClasses] = useState<Classroom[]>([])
  const [subjects, setSubjects] = useState<Subject[]>([])
  const [classId, setClassId] = useState(searchParams.get('classId') || '')
  const [subjectId, setSubjectId] = useState('')
  const [name, setName] = useState('')
  const [examType, setExamType] = useState<ExamType>('IN_CLASS')
  const [questionCount, setQuestionCount] = useState(10)
  const [answers, setAnswers] = useState<Array<{ value: string; points: number }>>(Array.from({ length: 10 }, () => ({ value: 'A', points: 1 })))
  const [answerText, setAnswerText] = useState('AAAAAAAAAA')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => { Promise.all([getClasses(), getSubjects()]).then(([loadedClasses, loadedSubjects]) => { setClasses(loadedClasses); setSubjects(loadedSubjects); if (!classId && loadedClasses[0]) setClassId(loadedClasses[0].id); if (loadedSubjects[0]) setSubjectId(loadedSubjects[0].id) }).catch((caught) => setError(caught instanceof Error ? caught.message : '加载考试配置失败')) }, [])
  const resizeQuestions = (value: number) => { const next = Math.min(100, Math.max(1, value || 1)); setQuestionCount(next); setAnswers((current) => Array.from({ length: next }, (_, index) => current[index] || { value: 'A', points: 1 })); setAnswerText((current) => current.replace(/[^A-D]/gi, '').toUpperCase().slice(0, next).padEnd(next, 'A')) }
  const applyAnswerText = (value: string) => { const normalized = value.replace(/[^A-D]/gi, '').toUpperCase().slice(0, 100); setAnswerText(normalized); if (!normalized) return; setQuestionCount(normalized.length); setAnswers((current) => Array.from({ length: normalized.length }, (_, index) => ({ value: normalized[index] || current[index]?.value || 'A', points: current[index]?.points || 1 }))) }
  const handleSubmit = async (event: FormEvent) => { event.preventDefault(); setError(null); setSubmitting(true); try { const session = await createSession({ class_id: classId, name: name.trim() || null, subject_id: subjectId || null, exam_type: examType, question_count: questionCount, answer_keys: answers.map((answer, index) => ({ question_no: index + 1, value: answer.value, points: answer.points })) }); await startSession(session.id); navigate(`/sessions/${session.id}/live`) } catch (caught) { setError(caught instanceof Error ? caught.message : '创建考试失败') } finally { setSubmitting(false) } }
  const totalScore = answers.reduce((total, answer) => total + answer.points, 0)
  return <div className="page-stack narrow-page"><PageHeading eyebrow="考试管理" title="新建考试" description="考试属于班级；先选择教师负责的班级、学科和考试类型，再录入 OMR 标准答案。" /><ErrorNotice message={error} /><form className="session-builder" onSubmit={handleSubmit}><section className="panel builder-section"><div className="section-number">01</div><div className="builder-content"><span className="eyebrow">考试信息</span><h2>这次考试面向哪个班？</h2><div className="form-grid"><label>考试名称<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：数学周测 1" required /></label><label>考试类型<select value={examType} onChange={(event) => setExamType(event.target.value as ExamType)}><option value="ENTRY">进门测</option><option value="IN_CLASS">随堂测</option><option value="EXIT">出门测</option><option value="CUSTOM">自定义测试</option></select></label><label>选择班级<select value={classId} onChange={(event) => setClassId(event.target.value)} required><option value="">请选择班级</option>{classes.filter((classroom) => classroom.status === 'ACTIVE').map((classroom) => <option value={classroom.id} key={classroom.id}>{classroom.name} · {classroom.student_count} 人</option>)}</select></label><label>学科<select value={subjectId} onChange={(event) => setSubjectId(event.target.value)} required><option value="">请选择学科</option>{subjects.map((subject) => <option value={subject.id} key={subject.id}>{subject.name}</option>)}</select></label></div></div></section><section className="panel builder-section"><div className="section-number">02</div><div className="builder-content"><span className="eyebrow">OMR 题目设置</span><h2>批量录入答案与分值</h2><div className="exam-builder-meta"><label className="question-count-field">题目数量<input type="number" min={1} max={100} value={questionCount} onChange={(event) => resizeQuestions(Number(event.target.value))} /><span>题</span></label><span className="score-total">总分 <b>{totalScore}</b></span></div><label>批量答案<input value={answerText} onChange={(event) => applyAnswerText(event.target.value)} placeholder="例如：ABCDABCDAB" inputMode="text" /><span className="form-hint">输入连续的 A/B/C/D，系统会自动生成逐题答案；本轮完整实现单选 OMR，数据模型已预留 OCR 题型。</span></label><div className="answer-key-list">{answers.map((answer, index) => <div className="answer-key-row" key={index}><span className="question-index">{String(index + 1).padStart(2, '0')}</span><span className="question-label">第 {index + 1} 题</span><div className="answer-options">{options.map((option) => <button type="button" key={option} className={answer.value === option ? 'answer-option answer-option-selected' : 'answer-option'} onClick={() => { setAnswers((current) => current.map((value, itemIndex) => itemIndex === index ? { ...value, value: option } : value)); setAnswerText((current) => current.split('').map((value, itemIndex) => itemIndex === index ? option : value).join('')) }}>{option}</button>)}</div><label className="points-input">分值<input type="number" min={0.5} max={1000} step={0.5} value={answer.points} onChange={(event) => setAnswers((current) => current.map((value, itemIndex) => itemIndex === index ? { ...value, points: Number(event.target.value) || 0.5 } : value))} /></label></div>)}</div></div></section><div className="builder-footer"><Link to="/dashboard" className="button button-ghost">取消</Link><button className="button button-primary button-large" disabled={submitting || !classId || !subjectId}>{submitting ? '正在保存…' : '保存并发布考试 →'}</button></div></form></div>
}

export function SessionsPage() {
  const [sessions, setSessions] = useState<AssessmentSession[]>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => { getSessions().then(setSessions).finally(() => setLoading(false)) }, [])
  return <div className="page-stack"><PageHeading eyebrow="考试数据" title="考试记录" description="每场考试都保存班级、学科、答案和结果快照，方便课后复盘。" action={<Link to="/sessions/new" className="button button-primary">+ 新建考试</Link>} />{loading ? <LoadingState /> : sessions.length ? <section className="panel session-history"><div className="history-head"><span>考试</span><span>班级 / 学科</span><span>状态</span><span>创建时间</span><span /></div>{sessions.map((session) => <div className="history-row" key={session.id}><div className="history-title"><span className={`session-mini-mark session-mini-${session.status.toLowerCase()}`}>{session.status === 'ACTIVE' ? '●' : '✓'}</span><div><strong>{session.name || '未命名考试'}</strong><small>{examTypeLabels[session.exam_type]} · {session.question_count} 题 · {session.total_score} 分</small></div></div><span>{session.class_name}{session.subject_name ? ` · ${session.subject_name}` : ''}</span><StatusBadge status={session.status} /><span className="muted-copy">{formatDate(session.created_at)}</span><div className="history-actions">{session.status === 'ACTIVE' ? <Link to={`/sessions/${session.id}/live`} className="button button-quiet">进入考试 →</Link> : <Link to={`/sessions/${session.id}/results`} className="button button-quiet">查看结果</Link>}</div></div>)}</section> : <EmptyState title="还没有考试记录" description="创建一场考试，开始积累机构学情数据。" action={<Link to="/sessions/new" className="button button-primary">创建考试</Link>} />}</div>
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
  const refresh = (quiet = false) => { if (!sessionId) return Promise.resolve(); if (!quiet) setLoading(true); return getResults(sessionId).then((loaded) => { setResult(loaded); setLastUpdated(new Date()); setError(null) }).catch((caught) => setError(caught instanceof Error ? caught.message : '加载考试数据失败')).finally(() => { if (!quiet) setLoading(false) }) }
  useEffect(() => { refresh(); if (!sessionId) return; const source = new EventSource(getStreamUrl(sessionId)); const onUpdate = () => refresh(true); source.addEventListener('session.update', onUpdate); source.onopen = () => setConnection('connected'); source.onerror = () => setConnection('reconnecting'); return () => { source.removeEventListener('session.update', onUpdate); source.close() } }, [sessionId])
  useEffect(() => { if (!result) return; const pending = result.students.filter((student) => student.status === 'PENDING'); setSelectedStudent((current) => current && pending.some((student) => student.student_id === current) ? current : pending[0]?.student_id || result.students[0]?.student_id || '') }, [result])
  useEffect(() => { if (!result) return; setMockAnswers(Object.fromEntries(result.questions.map((question) => [question.question_no, 'A']))) }, [result?.session.id])
  const pendingStudents = result?.students.filter((student) => student.status === 'PENDING') || []
  const handleMockSubmit = async (event: FormEvent) => { event.preventDefault(); if (!sessionId || !selectedStudent) return; setSubmitting(true); try { await submitAnswers(sessionId, { student_id: selectedStudent, answers: Object.entries(mockAnswers).map(([question_no, value]) => ({ question_no: Number(question_no), value })), review_required: reviewRequired }); await refresh(true) } catch (caught) { setError(caught instanceof Error ? caught.message : '模拟提交失败') } finally { setSubmitting(false) } }
  const handleClose = async () => { if (!sessionId || !window.confirm('确认结束这场考试？结束后不再接受新的提交，但仍可查看历史结果。')) return; try { await closeSession(sessionId); await refresh(true) } catch (caught) { setError(caught instanceof Error ? caught.message : '结束考试失败') } }
  const toggleOption = (questionNo: number) => setExpanded((current) => current.includes(questionNo) ? current.filter((item) => item !== questionNo) : [...current, questionNo])
  if (loading && !result) return <LoadingState label="正在连接考试数据…" />
  if (!result) return <><ErrorNotice message={error || '考试不存在'} /><Link to="/sessions" className="button button-secondary">返回考试记录</Link></>
  const session = result.session
  return <div className="page-stack live-page"><div className="live-page-header"><div><div className="breadcrumb"><Link to="/sessions">考试记录</Link><span>/</span>{session.class_name}</div><div className="live-title-line"><h1>{session.name || '未命名考试'}</h1><StatusBadge status={session.status} /></div><p>{session.class_name} · {session.subject_name || '未指定学科'} · {examTypeLabels[session.exam_type]} · {session.question_count} 道题 · {session.total_score} 分 · {formatFullDate(session.started_at || session.created_at)}</p></div><div className="button-row"><span className={`connection-state connection-${connection}`}><span />{connection === 'connected' ? '实时连接中' : '正在重连'}</span>{session.status === 'ACTIVE' ? <button className="button button-danger" onClick={handleClose}>结束考试</button> : <Link to={`/sessions/${session.id}/results`} className="button button-primary">查看完整结果 →</Link>}</div></div><ErrorNotice message={error} /><section className="live-summary-grid"><LiveSummary label="本场学生" value={result.participant_count} hint="考试名单快照" tone="neutral" /><LiveSummary label="已提交" value={result.submitted_count} hint={`${result.participant_count ? Math.round((result.submitted_count / result.participant_count) * 100) : 0}% 到达`} tone="green" /><LiveSummary label="未提交" value={result.pending_count} hint="需要关注" tone="gray" /><LiveSummary label="待复核" value={result.review_required_count} hint="识别或答题需确认" tone="orange" /></section><section className="panel status-panel"><div className="panel-heading"><div><span className="eyebrow">考试进度</span><h2>学生提交状态</h2></div><span className="live-updated"><span className="status-dot status-dot-live" />刚刚更新 {lastUpdated.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span></div><div className="student-status-grid">{result.students.map((student) => <div className={`student-status-card status-card-${student.status.toLowerCase()}`} key={student.student_id}><div className="student-status-top"><span className="student-avatar">{student.student_name.slice(0, 1)}</span><span className="status-card-icon">{student.status === 'PENDING' ? '○' : student.status === 'REVIEW_REQUIRED' ? '!' : '✓'}</span></div><strong>{student.student_name}</strong><small>{student.student_code}</small><span className="status-card-label">{student.status === 'PENDING' ? '未提交' : student.status === 'REVIEW_REQUIRED' ? '待复核' : '已提交'}</span></div>)}</div></section><div className="live-main-grid"><section className="panel question-stats-panel"><div className="panel-heading"><div><span className="eyebrow">实时分布</span><h2>每题答题情况</h2></div><span className="muted-copy">点击选项查看学生</span></div><div className="question-stats-list">{result.questions.map((question) => <QuestionStatCard key={question.question_no} question={question} expanded={expanded.includes(question.question_no)} onToggle={() => toggleOption(question.question_no)} />)}</div></section><section className="panel mock-panel"><div className="panel-heading"><div><span className="eyebrow">Development / Test</span><h2>识别联调</h2></div><span className="dev-badge">MOCK</span></div>{session.status === 'ACTIVE' ? <form className="stack-form" onSubmit={handleMockSubmit}><label>选择学生<select value={selectedStudent} onChange={(event) => setSelectedStudent(event.target.value)}>{pendingStudents.length ? pendingStudents.map((student) => <option key={student.student_id} value={student.student_id}>{student.student_name} · {student.student_code}</option>) : result.students.map((student) => <option key={student.student_id} value={student.student_id}>{student.student_name} · {student.student_code}</option>)}</select></label><div className="mock-answer-list">{result.questions.map((question) => <label key={question.question_no}>第 {question.question_no} 题<select value={mockAnswers[question.question_no] || 'A'} onChange={(event) => setMockAnswers((current) => ({ ...current, [question.question_no]: event.target.value }))}>{options.map((option) => <option value={option} key={option}>{option}</option>)}</select></label>)}</div><label className="check-row"><input type="checkbox" checked={reviewRequired} onChange={(event) => setReviewRequired(event.target.checked)} /><span>标记为待复核</span></label><button className="button button-primary button-full" disabled={submitting || !result.students.length}>{submitting ? '提交中…' : '模拟提交这份答题'}</button><p className="form-hint">此工具只用于开发联调；Android 后续使用同一套 Submission API。</p></form> : <div className="closed-callout"><span>✓</span><strong>考试已结束</strong><p>提交入口已关闭。你仍可以查看本场完整结果。</p><Link to={`/sessions/${session.id}/results`} className="button button-secondary">进入结果页</Link></div>}</section></div></div>
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
  return <div className="page-stack"><PageHeading eyebrow="考试复盘" title={session.name || '未命名考试'} description={`${session.class_name} · ${session.subject_name || '未指定学科'} · ${examTypeLabels[session.exam_type]} · ${formatFullDate(session.ended_at || session.created_at)}`} action={<div className="button-row"><Link to="/sessions" className="button button-secondary">返回考试</Link><button className="button button-quiet" onClick={() => exportSessionReport(session.id, 'score-sheet').catch((caught) => setError(caught instanceof Error ? caught.message : '导出失败'))}>成绩单 XLSX</button><button className="button button-quiet" onClick={() => exportSessionReport(session.id, 'subscore').catch((caught) => setError(caught instanceof Error ? caught.message : '导出失败'))}>小分表 XLSX</button><button className="button button-quiet" onClick={() => exportSessionReport(session.id, 'answer-stats').catch((caught) => setError(caught instanceof Error ? caught.message : '导出失败'))}>答题统计 XLSX</button>{session.status === 'CLOSED' && <button className="button button-primary" onClick={handleArchive} disabled={archiving}>{archiving ? '归档中…' : '归档考试'}</button>}</div>} /><ErrorNotice message={error} /><section className="result-hero"><div><span className="eyebrow eyebrow-light">本场考试总览</span><h2>全班答题完成度 <em>{result.participant_count ? Math.round((result.submitted_count / result.participant_count) * 100) : 0}%</em></h2><p>{result.submitted_count} 名学生提交，{result.pending_count} 名未提交 · 总分 {session.total_score}</p></div><div className="result-hero-metrics"><div><strong>{result.average_correct_rate}%</strong><span>平均正确率</span></div><div><strong>{result.review_required_count}</strong><span>待复核</span></div></div></section><section className="result-question-grid">{result.questions.map((question) => <QuestionStatCard key={question.question_no} question={question} expanded={false} onToggle={() => {}} />)}</section><section className="panel result-students-panel"><div className="panel-heading"><div><span className="eyebrow">个人明细</span><h2>学生考试结果</h2></div><span className="muted-copy">统一学生编号贯穿历史班级和考试</span></div><div className="result-table"><div className="result-table-head"><span>学生</span><span>状态</span><span>每题答案</span><span>得分 / 答对</span></div>{result.students.map((student) => <div className="result-table-row" key={student.student_id}><div className="student-identity"><span className="student-avatar">{student.student_name.slice(0, 1)}</span><div><strong>{student.student_name}</strong><small>{student.student_code}</small></div></div><StatusBadge status={student.status} /><div className="answer-pill-row">{session.questions.map((question) => <span className={`answer-pill ${student.answers?.[question.question_no] === question.correct_answer ? 'answer-pill-correct' : ''}`} key={question.question_no}>{student.answers?.[question.question_no] || '—'}</span>)}</div><strong>{student.score} / {student.correct_count} 题</strong></div>)}</div></section></div>
}
