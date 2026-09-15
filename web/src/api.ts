import type {
  AssessmentSession,
  ClassDetail,
  Classroom,
  CourseDay,
  Me,
  Organization,
  Results,
  Student,
  StudentImportPreview,
  StudentImportResult,
  Submission,
  Subject,
  Teacher,
  TimeSlot,
  User,
} from './types'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export const authStorageKey = 'classroom-assessment-access-token'
// Kept as a compatibility shim for the unmounted legacy settings component;
// tenant-scoped requests never read or send this value.
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
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
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

export async function login(organization_name: string, teacher_login_name: string, password: string): Promise<{ access_token: string; token_type: string; user: User; organization_id: string; organization_name: string; teacher_id: string; teacher_name: string; login_name: string; role: 'OWNER' | 'ADMIN' | 'TEACHER' }> {
  return request('/auth/login', { method: 'POST', body: JSON.stringify({ organization_name, teacher_login_name, password }) })
}

export function getMe(): Promise<Me> {
  return request('/me')
}

export function getOrganizations(): Promise<Organization[]> {
  return request('/organizations')
}

export function createOrganization(payload: { name: string; code_prefix?: string; organization_name?: string; student_code_label: string }): Promise<Organization> {
  return request('/organizations', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateOrganizationSettings(id: string, payload: { code_prefix?: string; organization_name: string; student_code_label: string; logo?: string | null }): Promise<Organization> {
  return request(`/organizations/${id}/settings`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function getClasses(): Promise<Classroom[]> {
  return request('/classes')
}

export function createClass(payload: { name: string; teacher_id?: string | null; school_stage?: string; grade?: string | null; day_of_week?: number | null; time_slot_id?: string | null }): Promise<Classroom> {
  return request('/classes', { method: 'POST', body: JSON.stringify(payload) })
}

export function getClass(id: string): Promise<ClassDetail> {
  return request(`/classes/${id}`)
}

export function updateClass(id: string, payload: { name?: string; teacher_id?: string | null; school_stage?: string; grade?: string | null; day_of_week?: number | null; time_slot_id?: string | null; status?: string }): Promise<Classroom> {
  return request(`/classes/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function getStudents(search = ''): Promise<Student[]> {
  const query = search ? `?search=${encodeURIComponent(search)}` : ''
  return request(`/students${query}`)
}

export function createStudent(payload: { name: string; school_stage?: string; gender?: string | null; phone?: string | null; parent_phone?: string | null; remark?: string | null; student_code?: string }): Promise<Student> {
  return request('/students', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateStudent(id: string, payload: { name?: string; school_stage?: string; gender?: string | null; phone?: string | null; parent_phone?: string | null; remark?: string | null; status?: string }): Promise<Student> {
  return request(`/students/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function bulkAddStudents(classId: string, students: Array<{ student_code?: string; name: string }>): Promise<Student[]> {
  return request(`/classes/${classId}/students`, { method: 'POST', body: JSON.stringify({ students }) })
}

export function addStudentToClass(classId: string, studentId: string, moveExisting = false): Promise<Student> {
  return request(`/classes/${classId}/students/${studentId}`, { method: 'POST', body: JSON.stringify({ move_existing: moveExisting }) })
}

export function removeStudentFromClass(classId: string, studentId: string): Promise<{ message: string }> {
  return request(`/classes/${classId}/students/${studentId}/remove`, { method: 'POST' })
}

export function bulkAttachStudents(classId: string, studentIds: string[]): Promise<Student[]> {
  return request(`/classes/${classId}/student-memberships`, { method: 'POST', body: JSON.stringify({ student_ids: studentIds }) })
}

export function transferStudent(studentId: string, targetClassId: string, fromClassId?: string): Promise<Student> {
  return request(`/students/${studentId}/transfer`, { method: 'POST', body: JSON.stringify({ target_class_id: targetClassId, from_class_id: fromClassId }) })
}

export function getTeachers(): Promise<Teacher[]> {
  return request('/teachers')
}

export function createTeacher(payload: { display_name: string; login_name: string; password: string; role: 'ADMIN' | 'TEACHER' }): Promise<Teacher> {
  return request('/teachers', { method: 'POST', body: JSON.stringify(payload) })
}

export function getSubjects(includeInactive = false): Promise<Subject[]> {
  return request(`/subjects${includeInactive ? '?include_inactive=true' : ''}`)
}

export function createSubject(payload: { name: string }): Promise<Subject> {
  return request('/subjects', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateSubject(id: string, payload: { name?: string; active?: boolean }): Promise<Subject> {
  return request(`/subjects/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function getTimeSlots(includeInactive = false): Promise<TimeSlot[]> {
  return request(`/time-slots${includeInactive ? '?include_inactive=true' : ''}`)
}

export function createTimeSlot(payload: { slot_code: string; display_name: string; start_time: string; end_time: string; applicable_school_stage?: string | null }): Promise<TimeSlot> {
  return request('/time-slots', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateTimeSlot(id: string, payload: { slot_code?: string; display_name?: string; start_time?: string; end_time?: string; applicable_school_stage?: string | null; active?: boolean }): Promise<TimeSlot> {
  return request(`/time-slots/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function getCourseDays(): Promise<CourseDay[]> {
  return request('/course-days')
}

export function createCourseDay(payload: { weekday: number; display_name: string }): Promise<CourseDay> {
  return request('/course-days', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateCourseDay(weekday: number, payload: { display_name?: string; status?: 'ACTIVE' | 'INACTIVE' }): Promise<CourseDay> {
  return request(`/course-days/${weekday}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export async function previewStudentImport(file: File): Promise<StudentImportPreview> {
  const form = new FormData()
  form.append('file', file)
  return request('/students/import/preview', { method: 'POST', body: form })
}

export function confirmStudentImport(payload: { class_id?: string; items: Array<{ row_number: number; name: string; school_stage: string; remark?: string | null; action: string; student_id?: string }> }): Promise<StudentImportResult> {
  return request('/students/import/confirm', { method: 'POST', body: JSON.stringify(payload) })
}

export function downloadFile(path: string, fallbackName: string): Promise<void> {
  return (async () => {
    const headers = new Headers()
    const token = getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const response = await fetch(`${API_BASE_URL}${path}`, { headers })
    if (!response.ok) throw new APIError(response.status, `导出失败（${response.status}）`)
    const blob = await response.blob()
    const disposition = response.headers.get('Content-Disposition') || ''
    const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
    const filename = encoded ? decodeURIComponent(encoded) : fallbackName
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    URL.revokeObjectURL(url)
  })()
}

export function exportStudents(): Promise<void> {
  return downloadFile('/students/export.xlsx', '机构学生库.xlsx')
}

export function exportStudentImportTemplate(): Promise<void> {
  return downloadFile('/students/import/template.xlsx', '学生名单模板.xlsx')
}

export function exportClass(classId: string): Promise<void> {
  return downloadFile(`/classes/${classId}/export.xlsx`, '班级学生名单.xlsx')
}

export function exportSessionReport(sessionId: string, reportType: 'score-sheet' | 'subscore' | 'answer-stats'): Promise<void> {
  const names = { 'score-sheet': '成绩单.xlsx', subscore: '小分表.xlsx', 'answer-stats': '答题统计.xlsx' }
  return downloadFile(`/sessions/${sessionId}/exports/${reportType}.xlsx`, names[reportType])
}

export function getSessions(): Promise<AssessmentSession[]> {
  return request('/sessions')
}

export function getSession(id: string): Promise<AssessmentSession> {
  return request(`/sessions/${id}`)
}

export function createSession(payload: { class_id: string; name: string | null; subject_id?: string | null; exam_type?: string; question_count: number; answer_keys: Array<{ question_no: number; value: string; points?: number; question_type?: string }> }): Promise<AssessmentSession> {
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
