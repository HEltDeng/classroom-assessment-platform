import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { ChalkboardTeacher, ClipboardText, Gear, House, SquaresFour, UsersThree, type IconProps } from '@phosphor-icons/react'
import { clearAuth, getMe, getToken, login } from './api'
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
  TeachersPage,
} from './pages'

interface AuthContextValue {
  me: Me | null
  loading: boolean
  refreshProfile: () => Promise<void>
  signIn: (organizationName: string, teacherLoginName: string, password: string) => Promise<void>
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
    signIn: async (organizationName, teacherLoginName, password) => {
      const result = await login(organizationName, teacherLoginName, password)
      localStorage.setItem('classroom-assessment-access-token', result.access_token)
      await refreshProfile()
    },
    signOut: () => {
      clearAuth()
      setMe(null)
    },
  }), [loading, me])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

type NavigationItem = { to: string; label: string; Icon: React.ComponentType<IconProps>; adminOnly?: boolean }

const navigation: NavigationItem[] = [
  { to: '/dashboard', label: '工作台', Icon: House },
  { to: '/teachers', label: '教师', Icon: ChalkboardTeacher, adminOnly: true },
  { to: '/classes', label: '班级', Icon: SquaresFour },
  { to: '/students', label: '学生库', Icon: UsersThree },
  { to: '/sessions', label: '考试', Icon: ClipboardText },
  { to: '/organizations', label: '系统设置', Icon: Gear, adminOnly: true },
]

function AppShell() {
  const { me, signOut } = useAuth()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const currentOrg = me?.organization
  const visibleNavigation = navigation.filter((item) => !item.adminOnly || me?.role === 'OWNER' || me?.role === 'ADMIN')
  const roleLabel = me?.role === 'TEACHER' ? '教师' : '管理员'

  return (
    <div className="app-shell">
      <aside className={`sidebar ${menuOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-org-name">{currentOrg?.name || '智慧课堂系统'}</div>
        <nav className="main-nav" aria-label="主导航">
          {visibleNavigation.map((item) => (
            <NavLink key={item.to} to={item.to} onClick={() => setMenuOpen(false)} className={({ isActive }) => `nav-item ${isActive ? 'nav-item-active' : ''}`}>
              <item.Icon className="nav-icon" size={21} weight="regular" /><span>{item.label}</span>
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
            <span className="topbar-kicker">{currentOrg?.name || '智慧课堂系统'}</span>
            <span className="topbar-divider">/</span>
            <span>{navigation.find((item) => location.pathname.startsWith(item.to))?.label || '工作台'}</span>
          </div>
          <div className="topbar-user">
            <div className="user-copy"><strong>{me?.display_name}</strong><span>{currentOrg?.name} · {roleLabel}</span></div>
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
  if (!me.organization_id || !me.teacher_id) return <Navigate to="/login" replace />
  return <AppShell />
}

function AdminOnlyRoute({ children }: { children: React.ReactNode }) {
  const { me } = useAuth()
  if (me?.role !== 'OWNER' && me?.role !== 'ADMIN') return <Navigate to="/dashboard" replace />
  return <>{children}</>
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
        <Route path="/organizations" element={<AdminOnlyRoute><OrganizationsPage /></AdminOnlyRoute>} />
        <Route path="/teachers" element={<AdminOnlyRoute><TeachersPage /></AdminOnlyRoute>} />
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
