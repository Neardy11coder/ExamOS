/**
 * Faculty Authoring API Client (M1-EXAM-UI-1).
 *
 * Implements:
 * - Topics:
 *     GET /api/v1/topics
 * - Questions:
 *     GET   /api/v1/questions
 *     POST  /api/v1/questions
 *     GET   /api/v1/questions/{id}
 *     PATCH /api/v1/questions/{id}
 *     POST  /api/v1/questions/{id}/archive
 * - Exams:
 *     GET    /api/v1/exams
 *     POST   /api/v1/exams
 *     GET    /api/v1/exams/{id}
 *     PATCH  /api/v1/exams/{id}
 *     POST   /api/v1/exams/{id}/questions
 *     PUT    /api/v1/exams/{id}/questions
 *     DELETE /api/v1/exams/{id}/questions/{question_id}
 *     POST   /api/v1/exams/{id}/publish
 *     POST   /api/v1/exams/{id}/unpublish
 */

import { ApiError, readCsrfCookie } from './auth';

const BASE = '/api/v1';

// ---------------------------------------------------------------------------
// Type Definitions
// ---------------------------------------------------------------------------

export interface TopicRead {
  id: string;
  code: string;
  name: string;
  subject: 'OS' | 'DBMS' | string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface QuestionOptionCreate {
  text: string;
  is_correct: boolean;
  display_order?: number;
}

export interface QuestionOptionRead {
  id: string;
  option_text: string;
  display_order: number;
  is_correct: boolean;
}

export interface QuestionCreate {
  prompt: string;
  topic_id?: string | null;
  options: QuestionOptionCreate[];
}

export interface QuestionUpdate {
  prompt?: string | null;
  topic_id?: string | null;
  options?: QuestionOptionCreate[] | null;
}

export interface QuestionRead {
  id: string;
  author_id: string;
  topic_id: string | null;
  prompt: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  options: QuestionOptionRead[];
  topic: TopicRead | null;
}

export interface ExamCreate {
  title: string;
  instructions?: string;
  duration_minutes: number;
}

export interface ExamUpdate {
  title?: string;
  instructions?: string;
  duration_minutes?: number;
}

export interface ExamQuestionAttach {
  question_id: string;
  marks?: number;
  display_order?: number;
}

export interface ExamQuestionReorderItem {
  question_id: string;
  marks: number;
  display_order: number;
}

export interface ExamQuestionOptionSnapshotRead {
  id: string;
  option_text_snapshot: string;
  display_order: number;
  is_correct: boolean;
}

export interface ExamQuestionSnapshotRead {
  id: string;
  source_question_id: string | null;
  prompt_snapshot: string;
  topic_code_snapshot: string | null;
  topic_name_snapshot: string | null;
  marks: string | number;
  display_order: number;
  options: ExamQuestionOptionSnapshotRead[];
}

export interface ExamDraftQuestionRead {
  id: string;
  source_question_id: string | null;
  prompt: string;
  topic_code: string | null;
  topic_name: string | null;
  marks: string | number;
  display_order: number;
  options_count: number;
}

export interface ExamRead {
  id: string;
  creator_id: string;
  title: string;
  instructions: string;
  duration_minutes: number;
  status: 'DRAFT' | 'PUBLISHED' | 'UNPUBLISHED' | string;
  question_count: number;
  total_marks: string | number;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExamDetailRead extends ExamRead {
  questions: (ExamQuestionSnapshotRead | ExamDraftQuestionRead)[];
}

export interface ExamPublishResponse {
  id: string;
  title: string;
  status: string;
  duration_minutes: number;
  question_count: number;
  total_marks: string | number;
  published_at: string;
}

export interface ExamUnpublishResponse {
  id: string;
  title: string;
  status: string;
  published_at: string | null;
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
    return new ApiError(res.status, message, code);
  } catch {
    return new ApiError(res.status, fallback);
  }
}

// ---------------------------------------------------------------------------
// Topic APIs
// ---------------------------------------------------------------------------

export async function apiGetTopics(): Promise<TopicRead[]> {
  const res = await fetch(`${BASE}/topics`, {
    method: 'GET',
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to fetch taxonomy topics.');
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Question Bank APIs
// ---------------------------------------------------------------------------

export async function apiGetQuestions(params?: {
  topic_id?: string;
  search?: string;
  include_archived?: boolean;
}): Promise<QuestionRead[]> {
  const searchParams = new URLSearchParams();
  if (params?.topic_id) searchParams.set('topic_id', params.topic_id);
  if (params?.search) searchParams.set('search', params.search);
  if (params?.include_archived !== undefined) {
    searchParams.set('include_archived', String(params.include_archived));
  }

  const qs = searchParams.toString();
  const url = `${BASE}/questions${qs ? `?${qs}` : ''}`;
  const res = await fetch(url, {
    method: 'GET',
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to fetch questions.');
  }
  return res.json();
}

export async function apiGetQuestion(id: string): Promise<QuestionRead> {
  const res = await fetch(`${BASE}/questions/${id}`, {
    method: 'GET',
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to retrieve question details.');
  }
  return res.json();
}

export async function apiCreateQuestion(
  payload: QuestionCreate,
  csrfToken?: string | null,
): Promise<QuestionRead> {
  const res = await fetch(`${BASE}/questions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to create question.');
  }
  return res.json();
}

export async function apiUpdateQuestion(
  id: string,
  payload: QuestionUpdate,
  csrfToken?: string | null,
): Promise<QuestionRead> {
  const res = await fetch(`${BASE}/questions/${id}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to update question.');
  }
  return res.json();
}

export async function apiArchiveQuestion(
  id: string,
  csrfToken?: string | null,
): Promise<QuestionRead> {
  const res = await fetch(`${BASE}/questions/${id}/archive`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to archive question.');
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Exam Management APIs
// ---------------------------------------------------------------------------

export async function apiGetExams(): Promise<ExamRead[]> {
  const res = await fetch(`${BASE}/exams`, {
    method: 'GET',
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to fetch examination list.');
  }
  return res.json();
}

export async function apiGetExam(id: string): Promise<ExamDetailRead> {
  const res = await fetch(`${BASE}/exams/${id}`, {
    method: 'GET',
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to fetch examination details.');
  }
  return res.json();
}

export async function apiCreateExam(
  payload: ExamCreate,
  csrfToken?: string | null,
): Promise<ExamRead> {
  const res = await fetch(`${BASE}/exams`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to create examination.');
  }
  return res.json();
}

export async function apiUpdateExam(
  id: string,
  payload: ExamUpdate,
  csrfToken?: string | null,
): Promise<ExamRead> {
  const res = await fetch(`${BASE}/exams/${id}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to update examination.');
  }
  return res.json();
}

export async function apiAttachQuestionToExam(
  examId: string,
  payload: ExamQuestionAttach,
  csrfToken?: string | null,
): Promise<ExamDetailRead> {
  const res = await fetch(`${BASE}/exams/${examId}/questions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to attach question to examination.');
  }
  return res.json();
}

export async function apiSetExamQuestions(
  examId: string,
  items: ExamQuestionReorderItem[],
  csrfToken?: string | null,
): Promise<ExamDetailRead> {
  const res = await fetch(`${BASE}/exams/${examId}/questions`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
    body: JSON.stringify(items),
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to update examination questions.');
  }
  return res.json();
}

export async function apiRemoveQuestionFromExam(
  examId: string,
  questionId: string,
  csrfToken?: string | null,
): Promise<ExamDetailRead> {
  const res = await fetch(`${BASE}/exams/${examId}/questions/${questionId}`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to remove question from examination.');
  }
  return res.json();
}

export async function apiPublishExam(
  examId: string,
  csrfToken?: string | null,
): Promise<ExamPublishResponse> {
  const res = await fetch(`${BASE}/exams/${examId}/publish`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to publish examination.');
  }
  return res.json();
}

export async function apiUnpublishExam(
  examId: string,
  csrfToken?: string | null,
): Promise<ExamUnpublishResponse> {
  const res = await fetch(`${BASE}/exams/${examId}/unpublish`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(csrfToken),
    },
    credentials: 'include',
  });
  if (!res.ok) {
    throw await extractApiError(res, 'Failed to unpublish examination.');
  }
  return res.json();
}
