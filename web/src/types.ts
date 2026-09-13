export type OrgStatus = 'ACTIVE' | 'ARCHIVED'
export type ClassStatus = 'ACTIVE' | 'ARCHIVED'
export type StudentStatus = 'ACTIVE' | 'INACTIVE'
export type SessionStatus = 'DRAFT' | 'ACTIVE' | 'CLOSED' | 'ARCHIVED'
export type SubmissionStatus = 'SUBMITTED' | 'REVIEW_REQUIRED'
export type SubmissionSource = 'mock' | 'android' | 'recognition'

export interface User {
  id: string
  email: string
  display_name: string
}

export interface OrganizationSettings {
  organization_name: string | null
  logo: string | null
  student_code_label: string
}

export interface Organization {
  id: string
  name: string
  status: OrgStatus
  settings: OrganizationSettings | null
  created_at: string
}

export interface Membership {
  organization_id: string
  role: 'OWNER' | 'ADMIN' | 'TEACHER'
  organization: Organization
}

export interface Me extends User {
  memberships: Membership[]
}

export interface Student {
  id: string
  organization_id: string
  student_code: string
  name: string
  status: StudentStatus
  created_at: string
}

export interface Classroom {
  id: string
  organization_id: string
  name: string
  status: ClassStatus
  student_count: number
  created_at: string
}

export interface ClassDetail extends Classroom {
  students: Student[]
}

export interface Question {
  id: string
  question_no: number
  question_type: 'MCQ' | 'TEXT'
  correct_answer: string
}

export interface AssessmentSession {
  id: string
  organization_id: string
  class_id: string
  class_name: string
  name: string | null
  question_count: number
  status: SessionStatus
  created_at: string
  started_at: string | null
  ended_at: string | null
  questions: Question[]
}

export interface Submission {
  id: string
  session_id: string
  student_id: string
  status: SubmissionStatus
  source: SubmissionSource
  is_update: boolean
  correct_count: number
  question_count: number
  submitted_at: string
  updated_at: string
}

export interface StudentLiveState {
  student_id: string
  student_code: string
  student_name: string
  status: 'PENDING' | SubmissionStatus
  submission_id: string | null
  source: SubmissionSource | null
  submitted_at: string | null
  answers: Record<number, string>
}

export interface QuestionStats {
  question_no: number
  correct_answer: string
  answered_count: number
  submitted_count: number
  counts: Record<'A' | 'B' | 'C' | 'D', number>
  correct_count: number
  correct_rate: number
  students_by_option: Record<'A' | 'B' | 'C' | 'D', string[]>
}

export interface Results {
  session: AssessmentSession
  participant_count: number
  submitted_count: number
  pending_count: number
  review_required_count: number
  average_correct_rate: number
  questions: QuestionStats[]
  students: StudentLiveState[]
}
