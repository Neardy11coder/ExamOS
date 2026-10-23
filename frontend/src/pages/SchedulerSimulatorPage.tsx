import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  Play,
  Plus,
  Trash2,
  Cpu,
  Clock,
  Layers,
  BarChart2,
  Info,
} from 'lucide-react';
import {
  apiSimulateScheduling,
  type JobInput,
  type ScheduleResult,
  type SchedulingAlgorithm,
} from '../api/scheduler';
import { ApiError } from '../api/auth';
import { InlineError, LoadingSpinner } from '../components/ui';

interface JobFormRow {
  key: string;
  id: string;
  arrival_time: string;
  burst_time: string;
  priority: string;
}

const PRESET_CASE_A: JobFormRow[] = [
  { key: '1', id: 'A', arrival_time: '0', burst_time: '3', priority: '2' },
  { key: '2', id: 'B', arrival_time: '5', burst_time: '2', priority: '1' },
];

const PRESET_CASE_B: JobFormRow[] = [
  { key: '1', id: 'A', arrival_time: '0', burst_time: '5', priority: '1' },
  { key: '2', id: 'B', arrival_time: '1', burst_time: '3', priority: '1' },
];

const PRESET_CASE_C: JobFormRow[] = [
  { key: '1', id: 'A', arrival_time: '0', burst_time: '4', priority: '3' },
  { key: '2', id: 'B', arrival_time: '1', burst_time: '2', priority: '1' },
  { key: '3', id: 'C', arrival_time: '1', burst_time: '1', priority: '2' },
];

const PRESET_SJF: JobFormRow[] = [
  { key: '1', id: 'A', arrival_time: '0', burst_time: '5', priority: '1' },
  { key: '2', id: 'B', arrival_time: '1', burst_time: '2', priority: '1' },
  { key: '3', id: 'C', arrival_time: '2', burst_time: '1', priority: '1' },
  { key: '4', id: 'D', arrival_time: '3', burst_time: '4', priority: '1' },
];

// Consistent palette for jobs in Gantt timeline
const JOB_COLORS: string[] = [
  '#6366f1', // Indigo
  '#06b6d4', // Cyan
  '#10b981', // Emerald
  '#f59e0b', // Amber
  '#ec4899', // Pink
  '#8b5cf6', // Violet
  '#14b8a6', // Teal
  '#f97316', // Orange
];

function getJobColor(jobId: string, index: number): string {
  if (!jobId) return '#334155';
  let hash = 0;
  for (let i = 0; i < jobId.length; i++) {
    hash = (hash << 5) - hash + jobId.charCodeAt(i);
    hash |= 0;
  }
  const colorIndex = Math.abs(hash + index) % JOB_COLORS.length;
  return JOB_COLORS[colorIndex];
}

export function SchedulerSimulatorPage() {
  const [algorithm, setAlgorithm] = useState<SchedulingAlgorithm>('FCFS');
  const [quantum, setQuantum] = useState<string>('2');
  const [jobs, setJobs] = useState<JobFormRow[]>(PRESET_CASE_A);
  const [result, setResult] = useState<ScheduleResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const isRoundRobin = algorithm === 'ROUND_ROBIN';
  const isPriority = algorithm === 'PRIORITY';

  function handleAddJob() {
    setFormError(null);
    const nextNum = jobs.length + 1;
    const nextKey = Math.random().toString(36).substring(2, 9);
    setJobs([
      ...jobs,
      {
        key: nextKey,
        id: `P${nextNum}`,
        arrival_time: '0',
        burst_time: '2',
        priority: '1',
      },
    ]);
  }

  function handleRemoveJob(key: string) {
    setFormError(null);
    if (jobs.length <= 1) {
      setFormError('Simulation requires at least 1 job.');
      return;
    }
    setJobs(jobs.filter((j) => j.key !== key));
  }

  function handleJobChange(key: string, field: keyof JobFormRow, value: string) {
    setFormError(null);
    setJobs(
      jobs.map((j) => {
        if (j.key === key) {
          return { ...j, [field]: value };
        }
        return j;
      }),
    );
  }

  function applyPreset(preset: JobFormRow[], algo: SchedulingAlgorithm, q?: string) {
    setFormError(null);
    setResult(null);
    setAlgorithm(algo);
    if (q) setQuantum(q);
    setJobs(
      preset.map((j) => ({
        ...j,
        key: Math.random().toString(36).substring(2, 9),
      })),
    );
  }

  async function handleSimulate(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    // Front-end sanity validation before dispatch
    if (jobs.length === 0) {
      setFormError('Job set cannot be empty.');
      return;
    }

    const seenIds = new Set<string>();
    const parsedJobs: JobInput[] = [];

    for (let i = 0; i < jobs.length; i++) {
      const row = jobs[i];
      const trimmedId = row.id.trim();
      if (!trimmedId) {
        setFormError(`Job at row ${i + 1} has an empty identifier.`);
        return;
      }
      if (seenIds.has(trimmedId)) {
        setFormError(`Duplicate job identifier '${trimmedId}' found.`);
        return;
      }
      seenIds.add(trimmedId);

      const arr = Number(row.arrival_time);
      if (isNaN(arr) || !Number.isInteger(arr) || arr < 0) {
        setFormError(`Job '${trimmedId}': Arrival time must be an integer >= 0.`);
        return;
      }

      const burst = Number(row.burst_time);
      if (isNaN(burst) || !Number.isInteger(burst) || burst < 1) {
        setFormError(`Job '${trimmedId}': Burst time must be an integer >= 1.`);
        return;
      }

      let prio: number | null = null;
      if (isPriority) {
        prio = Number(row.priority);
        if (isNaN(prio) || !Number.isInteger(prio)) {
          setFormError(`Job '${trimmedId}': Priority must be an integer for Priority Scheduling.`);
          return;
        }
      }

      parsedJobs.push({
        id: trimmedId,
        arrival_time: arr,
        burst_time: burst,
        priority: prio,
      });
    }

    let parsedQuantum: number | null = null;
    if (isRoundRobin) {
      parsedQuantum = Number(quantum);
      if (isNaN(parsedQuantum) || !Number.isInteger(parsedQuantum) || parsedQuantum < 1) {
        setFormError('Round Robin time quantum must be an integer >= 1.');
        return;
      }
    }

    setIsLoading(true);
    try {
      const res = await apiSimulateScheduling({
        algorithm,
        quantum: parsedQuantum,
        jobs: parsedJobs,
      });
      setResult(res);
    } catch (err) {
      if (err instanceof ApiError) {
        setFormError(err.message);
      } else {
        setFormError('Failed to run simulation. Please verify inputs.');
      }
    } finally {
      setIsLoading(false);
    }
  }

  // Pre-calculate unique jobs for Gantt color mapping
  const uniqueJobIds = Array.from(new Set(jobs.map((j) => j.id.trim()).filter(Boolean)));

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__left">
          <Link
            to="/dashboard"
            className="btn btn--ghost btn--sm"
            style={{ display: 'inline-flex', alignItems: 'center', gap: '0.375rem' }}
          >
            <ArrowLeft style={{ width: 16, height: 16 }} />
            Dashboard
          </Link>
          <span style={{ color: 'var(--color-text-muted)' }}>/</span>
          <span style={{ fontWeight: 600, color: 'var(--color-text)' }}>OS Scheduling Simulator</span>
        </div>
      </header>

      <main className="app-main" style={{ maxWidth: 1100, margin: '0 auto', width: '100%', padding: '1.5rem' }}>
        {/* Educational Disclosure Notice (§8 / FR-OSLAB-002) */}
        <div
          role="note"
          aria-label="Educational disclosure"
          style={{
            background: 'rgba(99, 102, 241, 0.08)',
            border: '1px solid rgba(99, 102, 241, 0.25)',
            borderRadius: 'var(--radius-lg)',
            padding: '1rem 1.25rem',
            marginBottom: '1.5rem',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '0.75rem',
          }}
        >
          <Info style={{ width: 20, height: 20, color: 'var(--color-accent-light)', flexShrink: 0, marginTop: 2 }} />
          <div>
            <div style={{ fontWeight: 600, color: 'var(--color-accent-light)', fontSize: '0.95rem' }}>
              Educational simulation of abstract jobs
            </div>
            <p style={{ margin: '0.25rem 0 0', color: 'var(--color-text-secondary)', fontSize: '0.875rem', lineHeight: 1.5 }}>
              This simulator calculates deterministic theoretical metrics for abstract processes (zero context-switch overhead). It does not represent real browser sessions or operating system kernel processes.
            </p>
          </div>
        </div>

        {/* Algorithm Selection & Presets */}
        <section
          style={{
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-lg)',
            padding: '1.25rem',
            marginBottom: '1.5rem',
          }}
        >
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <Cpu style={{ width: 20, height: 20, color: 'var(--color-accent)' }} />
              <label htmlFor="algo-selector" style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                Algorithm:
              </label>
              <select
                id="algo-selector"
                value={algorithm}
                onChange={(e) => {
                  setAlgorithm(e.target.value as SchedulingAlgorithm);
                  setResult(null);
                  setFormError(null);
                }}
                className="form-input"
                style={{ width: 'auto', minWidth: 220, padding: '0.375rem 0.75rem' }}
              >
                <option value="FCFS">FCFS (First-Come, First-Served)</option>
                <option value="SJF">SJF (Shortest Job First — Non-preemptive)</option>
                <option value="ROUND_ROBIN">Round Robin (Preemptive Time-Sharing)</option>
                <option value="PRIORITY">Priority Scheduling (Non-preemptive)</option>
              </select>
            </div>

            {isRoundRobin && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Clock style={{ width: 18, height: 18, color: 'var(--color-warning)' }} />
                <label htmlFor="rr-quantum" style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                  Time Quantum (Q):
                </label>
                <input
                  id="rr-quantum"
                  type="number"
                  min="1"
                  step="1"
                  value={quantum}
                  onChange={(e) => setQuantum(e.target.value)}
                  className="form-input"
                  style={{ width: 80, padding: '0.375rem 0.5rem', textAlign: 'center' }}
                />
              </div>
            )}
          </div>

          {/* Algorithm Educational Summary */}
          <div
            style={{
              marginTop: '1rem',
              paddingTop: '0.75rem',
              borderTop: '1px solid var(--color-border-subtle)',
              fontSize: '0.85rem',
              color: 'var(--color-text-secondary)',
            }}
          >
            {algorithm === 'FCFS' && (
              <span>
                <strong>FCFS:</strong> Non-preemptive. Serves ready jobs strictly by arrival time. Equal arrival times are resolved by input order.
              </span>
            )}
            {algorithm === 'SJF' && (
              <span>
                <strong>SJF:</strong> Non-preemptive. Selects the ready job with the shortest CPU burst. Ties are broken by arrival time, then input order.
              </span>
            )}
            {algorithm === 'ROUND_ROBIN' && (
              <span>
                <strong>Round Robin:</strong> Preemptive time-sharing. Jobs execute for up to quantum Q. At quantum expiry, newly arriving jobs enter the ready queue before the preempted job.
              </span>
            )}
            {algorithm === 'PRIORITY' && (
              <span>
                <strong>Priority:</strong> Non-preemptive. Selects the ready job with the lowest numeric priority value (smaller number = higher priority). Ties broken by arrival time, then input order.
              </span>
            )}
          </div>

          {/* Quick Presets */}
          <div style={{ marginTop: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', marginRight: '0.25rem' }}>
              Load preset case:
            </span>
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => applyPreset(PRESET_CASE_A, 'FCFS')}
            >
              Case A (FCFS + Idle)
            </button>
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => applyPreset(PRESET_CASE_B, 'ROUND_ROBIN', '2')}
            >
              Case B (RR Q=2)
            </button>
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => applyPreset(PRESET_CASE_C, 'PRIORITY')}
            >
              Case C (Priority)
            </button>
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => applyPreset(PRESET_SJF, 'SJF')}
            >
              Preset (SJF)
            </button>
          </div>
        </section>

        {/* Job Input Form */}
        <form onSubmit={handleSimulate}>
          <section
            style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-lg)',
              padding: '1.25rem',
              marginBottom: '1.5rem',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Layers style={{ width: 18, height: 18, color: 'var(--color-accent-light)' }} />
                <h2 style={{ fontSize: '1rem', margin: 0, fontWeight: 600 }}>Workload Processes</h2>
                <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
                  ({jobs.length} / 50 max)
                </span>
              </div>
              <button
                type="button"
                onClick={handleAddJob}
                className="btn btn--secondary btn--sm"
                disabled={jobs.length >= 50}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}
              >
                <Plus style={{ width: 14, height: 14 }} /> Add Process
              </button>
            </div>

            {formError && (
              <div style={{ marginBottom: '1rem' }}>
                <InlineError message={formError} />
              </div>
            )}

            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left', color: 'var(--color-text-secondary)' }}>
                    <th style={{ padding: '0.5rem' }}>ID</th>
                    <th style={{ padding: '0.5rem' }}>Arrival Time</th>
                    <th style={{ padding: '0.5rem' }}>Burst Time</th>
                    {isPriority && <th style={{ padding: '0.5rem' }}>Priority (Lower = Higher)</th>}
                    <th style={{ padding: '0.5rem', textAlign: 'right' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job, idx) => (
                    <tr key={job.key} style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
                      <td style={{ padding: '0.5rem' }}>
                        <input
                          type="text"
                          value={job.id}
                          aria-label={`Job ID row ${idx + 1}`}
                          onChange={(e) => handleJobChange(job.key, 'id', e.target.value)}
                          className="form-input"
                          style={{ width: 100, padding: '0.375rem 0.5rem', fontWeight: 600 }}
                        />
                      </td>
                      <td style={{ padding: '0.5rem' }}>
                        <input
                          type="number"
                          min="0"
                          step="1"
                          value={job.arrival_time}
                          aria-label={`Arrival time row ${idx + 1}`}
                          onChange={(e) => handleJobChange(job.key, 'arrival_time', e.target.value)}
                          className="form-input"
                          style={{ width: 110, padding: '0.375rem 0.5rem' }}
                        />
                      </td>
                      <td style={{ padding: '0.5rem' }}>
                        <input
                          type="number"
                          min="1"
                          step="1"
                          value={job.burst_time}
                          aria-label={`Burst time row ${idx + 1}`}
                          onChange={(e) => handleJobChange(job.key, 'burst_time', e.target.value)}
                          className="form-input"
                          style={{ width: 110, padding: '0.375rem 0.5rem' }}
                        />
                      </td>
                      {isPriority && (
                        <td style={{ padding: '0.5rem' }}>
                          <input
                            type="number"
                            step="1"
                            value={job.priority}
                            aria-label={`Priority row ${idx + 1}`}
                            onChange={(e) => handleJobChange(job.key, 'priority', e.target.value)}
                            className="form-input"
                            style={{ width: 110, padding: '0.375rem 0.5rem' }}
                          />
                        </td>
                      )}
                      <td style={{ padding: '0.5rem', textAlign: 'right' }}>
                        <button
                          type="button"
                          onClick={() => handleRemoveJob(job.key)}
                          disabled={jobs.length <= 1}
                          className="btn btn--ghost btn--sm"
                          style={{ color: 'var(--color-error)', opacity: jobs.length <= 1 ? 0.3 : 1 }}
                          aria-label={`Delete job ${job.id}`}
                        >
                          <Trash2 style={{ width: 16, height: 16 }} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ marginTop: '1.25rem', display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
              <button
                type="submit"
                disabled={isLoading}
                className="btn btn--primary"
                style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', minWidth: 160, justifyContent: 'center' }}
              >
                {isLoading ? <LoadingSpinner size="sm" label="Simulating…" /> : <Play style={{ width: 16, height: 16 }} />}
                Run Simulation
              </button>
            </div>
          </section>
        </form>

        {/* Results Section */}
        {result && (
          <section
            style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-lg)',
              padding: '1.5rem',
              animation: 'fadeIn 0.2s ease',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <BarChart2 style={{ width: 20, height: 20, color: 'var(--color-accent)' }} />
                <h2 style={{ fontSize: '1.1rem', margin: 0, fontWeight: 600 }}>Simulation Results</h2>
              </div>
              <span style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
                Algorithm: <strong>{result.algorithm}</strong>
                {result.quantum ? ` (Q=${result.quantum})` : ''}
              </span>
            </div>

            {/* Gantt Timeline Visualizer */}
            <div style={{ marginBottom: '2rem' }}>
              <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: '0.75rem' }}>
                Gantt Timeline Schedule
              </h3>

              <div
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-md)',
                  padding: '1rem',
                  overflowX: 'auto',
                }}
              >
                {/* Timeline Bar */}
                <div
                  style={{
                    display: 'flex',
                    minWidth: 600,
                    height: 48,
                    borderRadius: 'var(--radius-sm)',
                    overflow: 'hidden',
                    border: '1px solid var(--color-border-subtle)',
                  }}
                >
                  {result.timeline.map((seg, idx) => {
                    const duration = seg.end - seg.start;
                    const isIdle = seg.kind === 'IDLE';
                    const color = isIdle
                      ? '#1e293b'
                      : getJobColor(seg.job_id || '', uniqueJobIds.indexOf(seg.job_id || ''));

                    return (
                      <div
                        key={idx}
                        title={isIdle ? `IDLE: [${seg.start}, ${seg.end})` : `Job ${seg.job_id}: [${seg.start}, ${seg.end})`}
                        style={{
                          flex: duration,
                          minWidth: 40,
                          backgroundColor: color,
                          borderRight: '1px solid rgba(0,0,0,0.3)',
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: isIdle ? '#94a3b8' : '#ffffff',
                          fontWeight: 600,
                          fontSize: '0.85rem',
                          position: 'relative',
                          userSelect: 'none',
                        }}
                      >
                        <span>{isIdle ? 'IDLE' : seg.job_id}</span>
                        <span style={{ fontSize: '0.7rem', opacity: 0.8 }}>({duration})</span>
                      </div>
                    );
                  })}
                </div>

                {/* Timeline Axis Labels */}
                <div
                  style={{
                    display: 'flex',
                    minWidth: 600,
                    marginTop: '0.5rem',
                    position: 'relative',
                    height: 20,
                    fontSize: '0.75rem',
                    color: 'var(--color-text-muted)',
                  }}
                >
                  {result.timeline.map((seg, idx) => (
                    <div
                      key={idx}
                      style={{
                        flex: seg.end - seg.start,
                        minWidth: 40,
                        display: 'flex',
                        justifyContent: 'space-between',
                        padding: '0 2px',
                      }}
                    >
                      <span>{seg.start}</span>
                      {idx === result.timeline.length - 1 && <span>{seg.end}</span>}
                    </div>
                  ))}
                </div>

                {/* Timeline Legend */}
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem', marginTop: '1rem', fontSize: '0.8rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                    <span style={{ width: 12, height: 12, backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: 2 }} />
                    <span style={{ color: 'var(--color-text-muted)' }}>CPU Idle</span>
                  </div>
                  {uniqueJobIds.map((jid, i) => (
                    <div key={jid} style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                      <span style={{ width: 12, height: 12, backgroundColor: getJobColor(jid, i), borderRadius: 2 }} />
                      <span>{jid}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Overall Aggregate Statistics */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                gap: '1rem',
                marginBottom: '2rem',
              }}
            >
              <div style={{ background: 'var(--color-surface-2)', padding: '1rem', borderRadius: 'var(--radius-md)' }}>
                <div style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', marginBottom: '0.25rem' }}>
                  Average Waiting Time
                </div>
                <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--color-accent-light)' }}>
                  {result.average_waiting_time}
                </div>
              </div>
              <div style={{ background: 'var(--color-surface-2)', padding: '1rem', borderRadius: 'var(--radius-md)' }}>
                <div style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', marginBottom: '0.25rem' }}>
                  Average Turnaround Time
                </div>
                <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--color-text)' }}>
                  {result.average_turnaround_time}
                </div>
              </div>
              <div style={{ background: 'var(--color-surface-2)', padding: '1rem', borderRadius: 'var(--radius-md)' }}>
                <div style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', marginBottom: '0.25rem' }}>
                  Average Response Time
                </div>
                <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--color-text)' }}>
                  {result.average_response_time}
                </div>
              </div>
              <div style={{ background: 'var(--color-surface-2)', padding: '1rem', borderRadius: 'var(--radius-md)' }}>
                <div style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', marginBottom: '0.25rem' }}>
                  CPU Utilization
                </div>
                <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--color-success)' }}>
                  {result.cpu_utilization_percent}%
                </div>
              </div>
              <div style={{ background: 'var(--color-surface-2)', padding: '1rem', borderRadius: 'var(--radius-md)' }}>
                <div style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', marginBottom: '0.25rem' }}>
                  Throughput
                </div>
                <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--color-text)' }}>
                  {result.throughput} <span style={{ fontSize: '0.8rem', fontWeight: 400 }}>jobs/unit</span>
                </div>
              </div>
            </div>

            {/* Per-Job Metrics Table */}
            <div>
              <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: '0.75rem' }}>
                Per-Process Metrics Table
              </h3>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left', color: 'var(--color-text-secondary)' }}>
                      <th style={{ padding: '0.5rem' }}>Job ID</th>
                      <th style={{ padding: '0.5rem' }}>Arrival</th>
                      <th style={{ padding: '0.5rem' }}>Burst</th>
                      {isPriority && <th style={{ padding: '0.5rem' }}>Priority</th>}
                      <th style={{ padding: '0.5rem' }}>First Start</th>
                      <th style={{ padding: '0.5rem' }}>Completion</th>
                      <th style={{ padding: '0.5rem' }}>Turnaround (TAT)</th>
                      <th style={{ padding: '0.5rem' }}>Waiting (WT)</th>
                      <th style={{ padding: '0.5rem' }}>Response (RT)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.jobs.map((jm) => (
                      <tr key={jm.job_id} style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
                        <td style={{ padding: '0.5rem', fontWeight: 600 }}>{jm.job_id}</td>
                        <td style={{ padding: '0.5rem' }}>{jm.arrival_time}</td>
                        <td style={{ padding: '0.5rem' }}>{jm.burst_time}</td>
                        {isPriority && <td style={{ padding: '0.5rem' }}>{jm.priority}</td>}
                        <td style={{ padding: '0.5rem' }}>{jm.first_start_time}</td>
                        <td style={{ padding: '0.5rem' }}>{jm.completion_time}</td>
                        <td style={{ padding: '0.5rem', fontWeight: 600 }}>{jm.turnaround_time}</td>
                        <td style={{ padding: '0.5rem', fontWeight: 600, color: 'var(--color-accent-light)' }}>
                          {jm.waiting_time}
                        </td>
                        <td style={{ padding: '0.5rem' }}>{jm.response_time}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
