export type OrgStatus = 'ACTIVE' | 'ARCHIVED'
export type ClassStatus = 'ACTIVE' | 'ARCHIVED'
export type StudentStatus = 'ACTIVE' | 'INACTIVE'
export type SchoolStage = 'PRIMARY' | 'MIDDLE' | 'HIGH'
export type SessionStatus = 'DRAFT' | 'ACTIVE' | 'CLOSED' | 'ARCHIVED'
export type SubmissionStatus = 'SUBMITTED' | 'REVIEW_REQUIRED'
export type SubmissionSource = 'mock' | 'android' | 'recognition'
export type ExamType = 'ENTRY' | 'IN_CLASS' | 'EXIT' | 'CUSTOM'

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
  code_prefix: string
  student_serial: number
  status: OrgStatus
  settings: OrganizationSettings | null
  created_at: string
}

export interface Membership {
  organization_id: string
  login_name: string
  role: 'OWNER' | 'ADMIN' | 'TEACHER'
  organization: Organization
}

export interface Me extends User {
  organization_id: string
  teacher_id: string
  login_name: string
  role: 'OWNER' | 'ADMIN' | 'TEACHER'
  organization: Organization
  memberships: Membership[]
}

export interface Student {
  id: string
  organization_id: string
  student_code: string
  name: string
  school_stage: SchoolStage
  gender: string | null
  phone: string | null
  parent_phone: string | null
  remark: string | null
  status: StudentStatus
  created_at: string
  updated_at: string
}

export interface Classroom {
  id: string
  organization_id: string
  name: string
  teacher_id: string | null
  teacher_name: string | null
  school_stage: SchoolStage
  grade: string | null
  day_of_week: number | null
  time_slot_id: string | null
  time_slot_name: string | null
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
  question_type: 'SINGLE_CHOICE' | 'MULTIPLE_CHOICE' | 'TRUE_FALSE' | 'OCR_SHORT_ANSWER' | 'OCR_NUMBER' | 'OTHER' | 'MCQ' | 'TEXT'
  points: number
  correct_answer: string
}

export interface AssessmentSession {
  id: string
  organization_id: string
  class_id: string
  class_name: string
  subject_id: string | null
  subject_name: string | null
  exam_type: ExamType
  name: string | null
  question_count: number
  total_score: number
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
  score: number | null
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
  score: number
  correct_count: number
}

export interface QuestionStats {
  question_type: Question['question_type']
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

export interface Teacher {
  id: string
  user_id: string
  display_name: string
  login_name: string
  email: string
  role: 'OWNER' | 'ADMIN' | 'TEACHER'
  active: boolean
  class_count: number
}

export interface Subject {
  id: string
  organization_id: string
  name: string
  active: boolean
  created_at: string
}

export interface TimeSlot {
  id: string
  organization_id: string
  slot_code: string
  display_name: string
  start_time: string
  end_time: string
  applicable_school_stage: SchoolStage | null
  active: boolean
}

export interface CourseDay {
  id: string
  organization_id: string
  weekday: number
  display_name: string
  status: 'ACTIVE' | 'INACTIVE'
}

export type ImportItemStatus = 'PREPARE_CREATE' | 'EXISTING_SUSPECT' | 'DUPLICATE_IN_ORG' | 'DUPLICATE_INPUT' | 'EMPTY_NAME' | 'INVALID_STAGE'

export interface StudentImportMatch {
  id: string
  student_code: string
  name: string
  school_stage: SchoolStage
  current_classes: string[]
}

export interface StudentImportItem {
  row_number: number
  name: string
  school_stage: SchoolStage | null
  remark: string | null
  status: ImportItemStatus
  default_action: 'USE_EXISTING' | 'CREATE' | 'SKIP'
  matches: StudentImportMatch[]
  error: string | null
}

export interface StudentImportPreview {
  file_name: string
  total_rows: number
  existing_count: number
  prepare_create_count: number
  duplicate_count: number
  error_count: number
  items: StudentImportItem[]
}

export interface StudentImportResult {
  created_count: number
  reused_count: number
  skipped_count: number
  membership_added_count: number
  students: Student[]
}
