/**
 * OS CPU Scheduling Simulator API client (M2-OS-UI-1).
 *
 * Implements:
 * - POST /api/v1/scheduler/simulate
 */

import { ApiError, readCsrfCookie } from './auth';

const BASE = '/api/v1';

export type SchedulingAlgorithm = 'FCFS' | 'ROUND_ROBIN' | 'PRIORITY' | 'SJF';

export interface JobInput {
  id: string;
  arrival_time: number;
  burst_time: number;
  priority?: number | null;
}

export interface SchedulerRunRequest {
  algorithm: SchedulingAlgorithm;
  quantum?: number | null;
  jobs: JobInput[];
}

export interface TimelineSegment {
  job_id: string | null;
  start: number;
  end: number;
  kind: 'EXECUTION' | 'IDLE';
}

export interface JobMetrics {
  job_id: string;
  arrival_time: number;
  burst_time: number;
  priority?: number | null;
  first_start_time: number;
  completion_time: number;
  turnaround_time: number;
  waiting_time: number;
  response_time: number;
}

export interface ScheduleResult {
  algorithm: SchedulingAlgorithm;
  quantum?: number | null;
  jobs: JobMetrics[];
  timeline: TimelineSegment[];
  total_burst_time: number;
  earliest_arrival_time: number;
  latest_completion_time: number;
  measurement_window: number;
  cpu_utilization_percent: number;
  average_waiting_time: number;
  average_turnaround_time: number;
  average_response_time: number;
  throughput: number;
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

/**
 * Simulate CPU scheduling for abstract jobs.
 */
export async function apiSimulateScheduling(
  payload: SchedulerRunRequest,
  explicitCsrfToken?: string | null,
): Promise<ScheduleResult> {
  const csrfToken = explicitCsrfToken ?? readCsrfCookie() ?? '';

  const res = await fetch(`${BASE}/scheduler/simulate`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken,
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    throw await extractApiError(res, 'Scheduling simulation failed.');
  }

  return res.json();
}
