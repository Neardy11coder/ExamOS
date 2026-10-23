/**
 * Examination and student attempt API client (M1-STUD-UI-1).
 *
 * Implements:
 * - GET  /api/v1/exams/available
 * - POST /api/v1/exams/{exam_id}/attempts/start
 * - GET  /api/v1/attempts/{attempt_id}
 * - PUT  /api/v1/attempts/{attempt_id}/answers/{exam_question_id}
 * - POST /api/v1/attempts/{attempt_id}/submit
 * - GET  /api/v1/attempts/{attempt_id}/result
 *
 * Follows security and double-submit CSRF requirements:
 * - Cookies are sent via credentials: 'include'.
 * - State-changing calls (POST, PUT) pass X-CSRF-Token.
 * - Error formats match backend detail.error structure.
 */

import { ApiError, readCsrfCookie } from './auth';

const BASE = '/api/v1';

// ---------------------------------------------------------------------------
// TypeScript Interfaces matching Backend Pydantic Schemas
// ---------------------------------------------------------------------------

export interface AvailableExamItem {
  id: string;
  title: string;
  instructions: string;
  duration_minutes: number;
  question_count: number;
  total_marks: string | number;
  has_attempt: boolean;
  attempt_id: string | null;
  attempt_status: string | null; // 'IN_PROGRESS' | 'SUBMITTED' | 'EXPIRED' | null
}

export interface StudentOptionRead {
  id: string;
  text: string;
  display_order: number;
}

export interface StudentAnswerState {
  selected_option_id: string | null;
  marked_for_review: boolean;
  revision: number;
}

export interface StudentQuestionRead {
  exam_question_id: string;
  prompt: string;
  marks: string | number;
  display_order: number;
  options: StudentOptionRead[];
  answer: StudentAnswerState;
}

export interface AttemptExamInfo {
  id: string;
  title: string;
  instructions: string;
  duration_minutes: number;
  total_marks: string | number;
}

export interface AttemptDetailRead {
  attempt_id: string;
  status: string; // 'IN_PROGRESS' | 'SUBMITTED' | 'EXPIRED'
  started_at: string;
  deadline_at: string;
  remaining_seconds: number;
  exam: AttemptExamInfo;
  questions: StudentQuestionRead[];
}

export interface AnswerSaveRequest {
  selected_option_id: string | null;
  marked_for_review: boolean;
  expected_revision: number;
  mutation_id?: string | null;
}

export interface AnswerSaveResponse {
  selected_option_id: string | null;
  marked_for_review: boolean;
  revision: number;
  saved_at: string;
}

export interface SubmitAttemptRequest {
  submission_request_id?: string | null;
}

export interface SubmitAttemptResponse {
  attempt_id: string;
  status: string;
  score: string | number;
  total_marks: string | number;
  finalized_at: string;
}

export interface ResultOptionRead {
  id: string;
  text: string;
  display_order: number;
  is_correct: boolean;
}

export interface ResultQuestionItem {
  exam_question_id: string;
  prompt: string;
  marks: string | number;
  display_order: number;
  topic_code: string | null;
  topic_name: string | null;
  student_selected_option_id: string | null;
  is_correct: boolean;
  options: ResultOptionRead[];
}

export interface AttemptResultResponse {
  attempt_id: string;
  exam_id: string;
  exam_title: string;
  status: string;
  score: string | number;
  total_marks: string | number;
  percentage: string | number;
  started_at: string;
  deadline_at: string;
  finalized_at: string;
  questions: ResultQuestionItem[];
}

export class RevisionConflictError extends ApiError {
  constructor(
    message: string,
    public readonly canonicalState: {
      selected_option_id: string | null;
      marked_for_review: boolean;
      revision: number;
      saved_at: string;
    },
  ) {
    super(409, message, 'ANSWER_REVISION_CONFLICT');
    this.name = 'RevisionConflictError';
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getCsrfToken(explicitToken?: string | null): string {
  const token = explicitToken ?? readCsrfCookie();
  return token ?? '';
}

async function extractApiError(res: Response, fallback: string): Promise<ApiError> {
  try {
    const body = await res.json();
    const errObj = body?.detail?.error ?? body?.detail;
    const code = errObj?.code ?? body?.code;
    const message = errObj?.message ?? body?.message ?? fallback;

    if (res.status === 409 && code === 'ANSWER_REVISION_CONFLICT' && errObj?.details) {
      return new RevisionConflictError(message, errObj.details);
    }

    return new ApiError(res.status, message, code);
  } catch {
    return new ApiError(res.status, fallback);
  }
}

// ---------------------------------------------------------------------------
// Student Exam & Attempt API Functions
// ---------------------------------------------------------------------------

/**
 * Fetch available exams published for students.
 */
export async function apiGetAvailableExams(): Promise<AvailableExamItem[]> {
  const res = await fetch(`${BASE}/exams/available`, {
    method: 'GET',
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to fetch available exams.');
  }
  return res.json();
}

/**
 * Start or resume an examination attempt.
 */
export async function apiStartExamAttempt(
  examId: string,
  csrfToken?: string | null,
): Promise<AttemptDetailRead> {
  const res = await fetch(`${BASE}/exams/${examId}/attempts/start`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to start examination attempt.');
  }
  return res.json();
}

/**
 * Retrieve current workspace state for an attempt.
 */
export async function apiGetAttempt(attemptId: string): Promise<AttemptDetailRead> {
  const res = await fetch(`${BASE}/attempts/${attemptId}`, {
    method: 'GET',
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to load attempt.');
  }
  return res.json();
}

/**
 * Save answer option or review flag with optimistic revision.
 */
export async function apiSaveAnswer(
  attemptId: string,
  examQuestionId: string,
  payload: AnswerSaveRequest,
  csrfToken?: string | null,
): Promise<AnswerSaveResponse> {
  const res = await fetch(`${BASE}/attempts/${attemptId}/answers/${examQuestionId}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to save answer.');
  }
  return res.json();
}

/**
 * Submit an attempt.
 */
export async function apiSubmitAttempt(
  attemptId: string,
  payload?: SubmitAttemptRequest,
  csrfToken?: string | null,
): Promise<SubmitAttemptResponse> {
  const res = await fetch(`${BASE}/attempts/${attemptId}/submit`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
    body: JSON.stringify(payload ?? {}),
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to submit examination attempt.');
  }
  return res.json();
}

/**
 * Retrieve finalized examination result.
 */
export async function apiGetAttemptResult(attemptId: string): Promise<AttemptResultResponse> {
  const res = await fetch(`${BASE}/attempts/${attemptId}/result`, {
    method: 'GET',
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to retrieve examination results.');
  }
  return res.json();
}
