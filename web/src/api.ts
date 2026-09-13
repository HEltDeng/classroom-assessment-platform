import type {
  AssessmentSession,
  ClassDetail,
  Classroom,
  Me,
  Organization,
  Results,
  Student,
  Submission,
  User,
} from './types'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export const authStorageKey = 'classroom-assessment-access-token'
export const organizationStorageKey = 'classroom-assessment-organization-id'

export function getToken(): string | null {
  return localStorage.getItem(authStorageKey)
}

export function getOrganizationId(): string | null {
  return localStorage.getItem(organizationStorageKey)
}

export function setOrganizationId(id: string): void {
  localStorage.setItem(organizationStorageKey, id)
}

export class APIError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'APIError'
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const organizationId = getOrganizationId()
  if (organizationId) headers.set('X-Organization-Id', organizationId)
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const payload = await response.json() as { detail?: string }
      if (payload.detail) message = payload.detail
    } catch {
      // Keep the status-based message when the body is not JSON.
    }
    throw new APIError(response.status, message)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function login(email: string, password: string): Promise<{ access_token: string; user: User }> {
  return request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
}

export function getMe(): Promise<Me> {
  return request('/me')
}

export function getOrganizations(): Promise<Organization[]> {
  return request('/organizations')
}

export function createOrganization(payload: { name: string; organization_name?: string; student_code_label: string }): Promise<Organization> {
  return request('/organizations', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateOrganizationSettings(id: string, payload: { organization_name: string; student_code_label: string; logo?: string | null }): Promise<Organization> {
  return request(`/organizations/${id}/settings`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function getClasses(): Promise<Classroom[]> {
  return request('/classes')
}

export function createClass(name: string): Promise<Classroom> {
  return request('/classes', { method: 'POST', body: JSON.stringify({ name }) })
}

export function getClass(id: string): Promise<ClassDetail> {
  return request(`/classes/${id}`)
}

export function updateClass(id: string, payload: { name?: string; status?: string }): Promise<Classroom> {
  return request(`/classes/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function getStudents(search = ''): Promise<Student[]> {
  const query = search ? `?search=${encodeURIComponent(search)}` : ''
  return request(`/students${query}`)
}

export function createStudent(payload: { student_code: string; name: string }): Promise<Student> {
  return request('/students', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateStudent(id: string, payload: { student_code?: string; name?: string; status?: string }): Promise<Student> {
  return request(`/students/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function bulkAddStudents(classId: string, students: Array<{ student_code: string; name: string }>): Promise<Student[]> {
  return request(`/classes/${classId}/students`, { method: 'POST', body: JSON.stringify({ students }) })
}

export function addStudentToClass(classId: string, studentId: string, moveExisting = false): Promise<Student> {
  return request(`/classes/${classId}/students/${studentId}`, { method: 'POST', body: JSON.stringify({ move_existing: moveExisting }) })
}

export function removeStudentFromClass(classId: string, studentId: string): Promise<{ message: string }> {
  return request(`/classes/${classId}/students/${studentId}/remove`, { method: 'POST' })
}

export function getSessions(): Promise<AssessmentSession[]> {
  return request('/sessions')
}

export function getSession(id: string): Promise<AssessmentSession> {
  return request(`/sessions/${id}`)
}

export function createSession(payload: { class_id: string; name: string | null; question_count: number; answer_keys: Array<{ question_no: number; value: string }> }): Promise<AssessmentSession> {
  return request('/sessions', { method: 'POST', body: JSON.stringify(payload) })
}

export function startSession(id: string): Promise<AssessmentSession> {
  return request(`/sessions/${id}/start`, { method: 'POST' })
}

export function closeSession(id: string): Promise<AssessmentSession> {
  return request(`/sessions/${id}/close`, { method: 'POST' })
}

export function archiveSession(id: string): Promise<AssessmentSession> {
  return request(`/sessions/${id}/archive`, { method: 'POST' })
}

export function getResults(id: string): Promise<Results> {
  return request(`/sessions/${id}/results`)
}

export function submitAnswers(id: string, payload: { student_id: string; answers: Array<{ question_no: number; value: string }>; source?: string; review_required?: boolean }): Promise<Submission> {
  return request(`/sessions/${id}/submissions`, { method: 'POST', body: JSON.stringify({ source: 'mock', ...payload }) })
}

export function getStreamUrl(id: string): string {
  const token = getToken()
  return `${API_BASE_URL}/sessions/${id}/stream?access_token=${encodeURIComponent(token || '')}`
}

export function clearAuth(): void {
  localStorage.removeItem(authStorageKey)
}

