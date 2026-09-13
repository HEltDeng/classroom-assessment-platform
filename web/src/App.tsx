import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { clearAuth, getMe, getOrganizationId, getToken, login, organizationStorageKey, setOrganizationId } from './api'
import type { Me } from './types'
import {
  ClassesPage,
  ClassDetailPage,
  DashboardPage,
  LiveSessionPage,
  LoginPage,
  NewSessionPage,
  OrganizationsPage,
  ResultsPage,
  SessionsPage,
  StudentsPage,
} from './pages'

interface AuthContextValue {
  me: Me | null
  loading: boolean
  refreshProfile: () => Promise<void>
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}

function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(Boolean(getToken()))

  const refreshProfile = async () => {
    const profile = await getMe()
    setMe(profile)
    const savedOrg = getOrganizationId()
    const hasSavedOrg = profile.memberships.some((membership) => membership.organization_id === savedOrg)
    if (!hasSavedOrg && profile.memberships[0]) setOrganizationId(profile.memberships[0].organization_id)
  }

  useEffect(() => {
    if (!getToken()) return
    refreshProfile().catch(() => {
      clearAuth()
      setMe(null)
    }).finally(() => setLoading(false))
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    me,
    loading,
    refreshProfile,
    signIn: async (email, password) => {
      const result = await login(email, password)
      localStorage.setItem('classroom-assessment-access-token', result.access_token)
      await refreshProfile()
    },
    signOut: () => {
      clearAuth()
      localStorage.removeItem(organizationStorageKey)
      setMe(null)
    },
  }), [loading, me])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

const navigation = [
  { to: '/dashboard', label: '总览', icon: '⌂' },
  { to: '/classes', label: '班级', icon: '▦' },
  { to: '/students', label: '学生', icon: '◉' },
  { to: '/sessions', label: '课堂记录', icon: '◷' },
  { to: '/organizations', label: '机构设置', icon: '⚙' },
]

function AppShell() {
  const { me, signOut } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const memberships = me?.memberships ?? []
  const currentOrgId = getOrganizationId() || memberships[0]?.organization_id || ''
  const currentOrg = memberships.find((membership) => membership.organization_id === currentOrgId)?.organization || memberships[0]?.organization

  const chooseOrganization = (organizationId: string) => {
    setOrganizationId(organizationId)
    navigate('/dashboard')
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${menuOpen ? 'sidebar-open' : ''}`}>
        <div className="brand-lockup">
          <div className="brand-mark">答</div>
          <div>
            <strong>课堂答题台</strong>
            <span>实时学情工作台</span>
          </div>
        </div>
        <div className="org-switcher sidebar-org-switcher">
          <span className="eyebrow">当前机构</span>
          <select value={currentOrgId} onChange={(event) => chooseOrganization(event.target.value)} aria-label="选择机构">
            {memberships.map((membership) => <option key={membership.organization_id} value={membership.organization_id}>{membership.organization.name}</option>)}
          </select>
        </div>
        <nav className="main-nav" aria-label="主导航">
          {navigation.map((item) => (
            <NavLink key={item.to} to={item.to} onClick={() => setMenuOpen(false)} className={({ isActive }) => `nav-item ${isActive ? 'nav-item-active' : ''}`}>
              <span className="nav-icon">{item.icon}</span><span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footnote">
          <span className="status-dot status-dot-live" /> 数据实时同步
        </div>
      </aside>
      {menuOpen && <button className="sidebar-scrim" aria-label="关闭菜单" onClick={() => setMenuOpen(false)} />}
      <main className="main-area">
        <header className="topbar">
          <button className="mobile-menu-button" onClick={() => setMenuOpen(true)} aria-label="打开菜单">☰</button>
          <div className="topbar-context">
            <span className="topbar-kicker">{currentOrg?.name || '未选择机构'}</span>
            <span className="topbar-divider">/</span>
            <span>{navigation.find((item) => location.pathname.startsWith(item.to))?.label || '工作台'}</span>
          </div>
          <div className="topbar-user">
            <div className="avatar">{me?.display_name.slice(0, 1) || '师'}</div>
            <div className="user-copy"><strong>{me?.display_name}</strong><span>教师账户</span></div>
            <button className="text-button" onClick={signOut}>退出</button>
          </div>
        </header>
        <div className="page-content"><Outlet /></div>
      </main>
    </div>
  )
}

function ProtectedLayout() {
  const { me, loading } = useAuth()
  if (loading) return <div className="center-state"><div className="spinner" /><p>正在恢复工作台…</p></div>
  if (!me) return <Navigate to="/login" replace />
  return <AppShell />
}

function AppRoutes() {
  const { me, loading, signIn } = useAuth()
  if (loading) return <div className="center-state"><div className="spinner" /><p>正在加载…</p></div>
  return (
    <Routes>
      <Route path="/login" element={me ? <Navigate to="/dashboard" replace /> : <LoginPage onLogin={signIn} />} />
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/organizations" element={<OrganizationsPage />} />
        <Route path="/classes" element={<ClassesPage />} />
        <Route path="/classes/:classId" element={<ClassDetailPage />} />
        <Route path="/students" element={<StudentsPage />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route path="/sessions/new" element={<NewSessionPage />} />
        <Route path="/sessions/:sessionId/live" element={<LiveSessionPage />} />
        <Route path="/sessions/:sessionId/results" element={<ResultsPage />} />
      </Route>
      <Route path="*" element={<Navigate to={me ? '/dashboard' : '/login'} replace />} />
    </Routes>
  )
}

export default function App() {
  return <AuthProvider><BrowserRouter><AppRoutes /></BrowserRouter></AuthProvider>
}

