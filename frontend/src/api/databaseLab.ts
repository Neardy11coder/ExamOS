/**
 * Database Performance Lab API client (M3-DB-UI-1 / docs/04_API_CONTRACT.md § 7).
 *
 * Implements:
 * - GET /api/v1/labs/db/benchmarks (fetch scenarios catalog and dataset sizes)
 * - POST /api/v1/labs/db/benchmarks/run (execute approved benchmark)
 * - GET /api/v1/labs/db/benchmarks/runs (list benchmark history)
 * - GET /api/v1/labs/db/benchmarks/runs/:runId (retrieve run details)
 */

import { ApiError, readCsrfCookie } from './auth';

const BASE = '/api/v1';

export interface BenchmarkScenarioSummary {
  scenario_id: string;
  title: string;
  description: string;
  learning_objective: string;
  relevant_tables: string[];
  allowed_dataset_sizes: string[];
  default_parameters: Record<string, any>;
  index_explanation: string;
  caveat_notes: string;
}

export interface DatasetSizeOption {
  size_key: string;
  label: string;
  student_count: number;
  enrollments_per_student: number;
}

export interface BenchmarkCatalogResponse {
  scenarios: BenchmarkScenarioSummary[];
  dataset_sizes: DatasetSizeOption[];
}

export interface BenchmarkRunRequest {
  scenario_id: string;
  dataset_size: string;
  seed: number;
  repetitions: number;
  custom_parameters?: Record<string, any> | null;
}

export interface SingleVariantExecutionData {
  variant: string;
  query_text: string;
  plan: Record<string, any>;
  execution_time_ms: number;
  planning_time_ms: number;
  repetition_times_ms: number[];
  median_time_ms: number;
  row_count: number;
}

export interface BenchmarkExecutionResponse {
  run_id: string;
  scenario_id: string;
  dataset_size: string;
  seed: number;
  repetitions: number;
  postgres_version: string;
  no_index: SingleVariantExecutionData;
  indexed: SingleVariantExecutionData;
  speedup_ratio: number;
  index_explanation: string;
  caveat_notes: string;
  created_at: string;
}

export interface BenchmarkRunHistoryItem {
  run_id: string;
  scenario_code: string;
  dataset_size: string;
  seed: number;
  variant: string;
  status: string;
  speedup_ratio?: number | null;
  no_index_median_ms?: number | null;
  indexed_median_ms?: number | null;
  created_at: string;
}

async function extractApiError(res: Response, fallback: string): Promise<ApiError> {
  try {
    const body = await res.json();
    const errObj = body?.detail?.error ?? body?.detail ?? body?.error;
    const code = errObj?.code ?? body?.code;
    const message = errObj?.message ?? body?.message ?? fallback;
    return new ApiError(res.status, message, code);
  } catch {
    return new ApiError(res.status, fallback);
  }
}

/**
 * Fetch approved benchmark catalog scenarios and supported dataset scales.
 */
export async function apiGetBenchmarkCatalog(): Promise<BenchmarkCatalogResponse> {
  const res = await fetch(`${BASE}/labs/db/benchmarks`, {
    method: 'GET',
    credentials: 'include',
    headers: {
      Accept: 'application/json',
    },
  });

  if (!res.ok) {
    throw await extractApiError(res, 'Failed to load benchmark catalog.');
  }

  return res.json();
}

/**
 * Execute an approved benchmark scenario against isolated examos_lab datasets.
 */
export async function apiRunBenchmark(
  payload: BenchmarkRunRequest,
  explicitCsrfToken?: string | null,
): Promise<BenchmarkExecutionResponse> {
  const csrfToken = explicitCsrfToken ?? readCsrfCookie() ?? '';

  const res = await fetch(`${BASE}/labs/db/benchmarks/run`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken,
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    throw await extractApiError(res, 'Failed to execute benchmark.');
  }

  return res.json();
}

/**
 * Retrieve recent benchmark execution audit history.
 */
export async function apiGetBenchmarkHistory(limit = 20): Promise<BenchmarkRunHistoryItem[]> {
  const res = await fetch(`${BASE}/labs/db/benchmarks/runs?limit=${limit}`, {
    method: 'GET',
    credentials: 'include',
    headers: {
      Accept: 'application/json',
    },
  });

  if (!res.ok) {
    throw await extractApiError(res, 'Failed to load benchmark history.');
  }

  return res.json();
}

/**
 * Fetch full details and execution plan for a specific benchmark run.
 */
export async function apiGetBenchmarkRunDetail(runId: string): Promise<BenchmarkExecutionResponse> {
  const res = await fetch(`${BASE}/labs/db/benchmarks/runs/${runId}`, {
    method: 'GET',
    credentials: 'include',
    headers: {
      Accept: 'application/json',
    },
  });

  if (!res.ok) {
    throw await extractApiError(res, 'Failed to load benchmark run details.');
  }

  return res.json();
}
