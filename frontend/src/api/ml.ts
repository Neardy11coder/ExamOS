/**
 * ML Topic Suggestion API client (M4-ML-UI-1 / docs/04_API_CONTRACT.md §8).
 *
 * Implements:
 *   POST /api/v1/ml/topic-suggestions
 *
 * Design rules (docs/07_AI_ML_DESIGN.md §5):
 * - Never sends is_correct flags or answer keys; only prompt and option text.
 * - The endpoint always returns HTTP 200; available=false is a normal no-suggestion outcome.
 * - Network and API errors are surfaced as ApiError but must never block question saving.
 * - The returned topic_code is advisory only; the caller must map it to a loaded topic UUID.
 */

import { ApiError, readCsrfCookie } from './auth';

const BASE = '/api/v1';

// ---------------------------------------------------------------------------
// Types — mirror backend schemas/ml.py
// ---------------------------------------------------------------------------

export interface TopicSuggestionRequest {
  /** Question prompt text (max 5000 characters). */
  prompt: string;
  /** Option texts only — no correctness flags (max 10 options). */
  options?: string[];
}

export interface TopicSuggestionDetails {
  topic_code: string;
  topic_name: string;
  /** Predicted class probability [0.0, 1.0]. */
  confidence: number;
  /** Configured confidence threshold that was applied. */
  threshold: number;
}

/** Response when the model returns a high-confidence suggestion. */
export interface TopicSuggestionAvailable {
  available: true;
  suggestion: TopicSuggestionDetails;
  reason?: null;
}

/** Response when the model is absent, low-confidence, or an inference error occurred. */
export interface TopicSuggestionUnavailable {
  available: false;
  suggestion?: null;
  reason: 'MODEL_NOT_FOUND' | 'MODEL_LOAD_FAILED' | 'LOW_CONFIDENCE' | 'INFERENCE_FAILED' | 'MODEL_ERROR' | string;
}

export type TopicSuggestionResponse = TopicSuggestionAvailable | TopicSuggestionUnavailable;

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------

/**
 * Request an advisory ML topic suggestion from the backend.
 *
 * Always resolves (never rejects) for valid HTTP responses — the endpoint
 * returns HTTP 200 even when no suggestion is available.
 *
 * @throws {ApiError} on unexpected HTTP error (e.g. 401, 403, 422, 5xx).
 *   The caller should catch this and show a non-blocking suggestion error,
 *   NOT treat it as a question-form validation error.
 */
export async function apiGetTopicSuggestion(
  request: TopicSuggestionRequest,
  csrfToken?: string | null,
): Promise<TopicSuggestionResponse> {
  const token = csrfToken ?? readCsrfCookie() ?? '';

  // Strip correctness information — only send text.
  const body: TopicSuggestionRequest = {
    prompt: request.prompt,
    ...(request.options && request.options.length > 0
      ? { options: request.options }
      : {}),
  };

  const res = await fetch(`${BASE}/ml/topic-suggestions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': token,
    },
    credentials: 'include',
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    let message = `Topic suggestion request failed (HTTP ${res.status}).`;
    try {
      const errBody = await res.json();
      message =
        errBody?.detail?.error?.message ??
        errBody?.detail?.message ??
        errBody?.message ??
        message;
    } catch {
      // Ignore JSON parse failure
    }
    throw new ApiError(res.status, message);
  }

  return res.json() as Promise<TopicSuggestionResponse>;
}
