import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  Database,
  Play,
  History,
  Layers,
  Info,
  Clock,
  AlertTriangle,
  RotateCcw,
} from 'lucide-react';
import {
  apiGetBenchmarkCatalog,
  apiGetBenchmarkHistory,
  apiGetBenchmarkRunDetail,
  apiRunBenchmark,
  type BenchmarkCatalogResponse,
  type BenchmarkExecutionResponse,
  type BenchmarkRunHistoryItem,
  type BenchmarkScenarioSummary,
} from '../api/databaseLab';
import { ApiError } from '../api/auth';
import { InlineError, LoadingSpinner } from '../components/ui';

export function DatabaseLabPage() {
  const [catalog, setCatalog] = useState<BenchmarkCatalogResponse | null>(null);
  const [history, setHistory] = useState<BenchmarkRunHistoryItem[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>('selective_lookup');
  const [selectedSize, setSelectedSize] = useState<string>('medium');
  const [seed, setSeed] = useState<number>(42);
  const [repetitions, setRepetitions] = useState<number>(3);
  const [activeTab, setActiveTab] = useState<'workspace' | 'history'>('workspace');

  const [isLoadingCatalog, setIsLoadingCatalog] = useState<boolean>(true);
  const [isExecuting, setIsExecuting] = useState<boolean>(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [executionResult, setExecutionResult] = useState<BenchmarkExecutionResponse | null>(null);
  const [selectedHistoryRun, setSelectedHistoryRun] = useState<BenchmarkExecutionResponse | null>(null);
  const [viewingPlanVariant, setViewingPlanVariant] = useState<'both' | 'no_index' | 'indexed'>('both');

  useEffect(() => {
    loadCatalogAndInitialHistory();
  }, []);

  async function loadCatalogAndInitialHistory() {
    setIsLoadingCatalog(true);
    setErrorMessage(null);
    try {
      const [cat, hist] = await Promise.all([
        apiGetBenchmarkCatalog(),
        apiGetBenchmarkHistory(10),
      ]);
      setCatalog(cat);
      setHistory(hist);
      if (cat.scenarios.length > 0) {
        setSelectedScenarioId(cat.scenarios[0].scenario_id);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Failed to load database lab catalog.');
      }
    } finally {
      setIsLoadingCatalog(false);
    }
  }

  async function refreshHistory() {
    setIsLoadingHistory(true);
    try {
      const hist = await apiGetBenchmarkHistory(20);
      setHistory(hist);
    } catch {
      // Non-fatal history refresh
    } finally {
      setIsLoadingHistory(false);
    }
  }

  const currentScenario: BenchmarkScenarioSummary | undefined = catalog?.scenarios.find(
    (s) => s.scenario_id === selectedScenarioId,
  );

  async function handleExecute(e: React.FormEvent) {
    e.preventDefault();
    setErrorMessage(null);

    if (repetitions < 1 || repetitions > 10) {
      setErrorMessage('Repetitions must be an integer between 1 and 10.');
      return;
    }

    setIsExecuting(true);
    try {
      const res = await apiRunBenchmark({
        scenario_id: selectedScenarioId,
        dataset_size: selectedSize,
        seed: Number(seed) || 42,
        repetitions: Number(repetitions) || 3,
      });
      setExecutionResult(res);
      setSelectedHistoryRun(null);
      refreshHistory();
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Benchmark execution failed. Please verify database connection.');
      }
    } finally {
      setIsExecuting(false);
    }
  }

  async function handleLoadHistoryDetail(runId: string) {
    setErrorMessage(null);
    try {
      const res = await apiGetBenchmarkRunDetail(runId);
      setSelectedHistoryRun(res);
      setExecutionResult(null);
      setActiveTab('workspace');
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Failed to load historic run details.');
      }
    }
  }

  const activeResult = executionResult || selectedHistoryRun;

  return (
    <div className="app-shell">
      {/* Header */}
      <header className="app-header">
        <div className="app-header__left" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <Link
            to="/dashboard"
            className="btn btn--ghost btn--sm"
            style={{ display: 'inline-flex', alignItems: 'center', gap: '0.375rem' }}
          >
            <ArrowLeft style={{ width: 16, height: 16 }} />
            Dashboard
          </Link>
          <span style={{ color: 'var(--color-text-muted)' }}>/</span>
          <span style={{ fontWeight: 600, color: 'var(--color-text)' }}>Database Performance Lab</span>
        </div>
      </header>

      {/* Main Content */}
      <main className="app-main" id="main-content" style={{ maxWidth: '1280px', margin: '0 auto', width: '100%', padding: '1.5rem' }}>
        {/* Hero Section */}
        <div style={{ marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
            <div style={{ padding: '0.5rem', background: 'rgba(99, 102, 241, 0.15)', borderRadius: '0.5rem', color: 'var(--color-accent)' }}>
              <Database style={{ width: 24, height: 24 }} />
            </div>
            <div>
              <h1 style={{ fontSize: '1.5rem', fontWeight: 700, margin: 0, color: 'var(--color-text)' }}>
                Database Performance Benchmark Visualizer
              </h1>
              <p style={{ margin: 0, fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>
                Educational PostgreSQL execution engine in isolated <code style={{ color: '#818cf8', background: 'rgba(129, 140, 248, 0.1)', padding: '0.1rem 0.3rem', borderRadius: '4px' }}>examos_lab</code>. Compares query execution plans, timings, and buffer utilization across paired indexed and non-indexed tables.
              </p>
            </div>
          </div>
        </div>

        {/* Global Error Banner */}
        {errorMessage && (
          <div style={{ marginBottom: '1.25rem' }}>
            <InlineError message={errorMessage} />
          </div>
        )}

        {/* Navigation Tabs */}
        <div style={{ display: 'flex', gap: '0.5rem', borderBottom: '1px solid var(--color-border)', marginBottom: '1.5rem' }}>
          <button
            type="button"
            className={`btn btn--sm ${activeTab === 'workspace' ? 'btn--primary' : 'btn--ghost'}`}
            onClick={() => setActiveTab('workspace')}
            style={{ borderRadius: '0.375rem 0.375rem 0 0', display: 'flex', alignItems: 'center', gap: '0.375rem' }}
          >
            <Play style={{ width: 14, height: 14 }} />
            Benchmark Workspace
          </button>
          <button
            type="button"
            className={`btn btn--sm ${activeTab === 'history' ? 'btn--primary' : 'btn--ghost'}`}
            onClick={() => {
              setActiveTab('history');
              refreshHistory();
            }}
            style={{ borderRadius: '0.375rem 0.375rem 0 0', display: 'flex', alignItems: 'center', gap: '0.375rem' }}
          >
            <History style={{ width: 14, height: 14 }} />
            Execution History ({history.length})
          </button>
        </div>

        {isLoadingCatalog ? (
          <div style={{ padding: '4rem 0', display: 'flex', justifyContent: 'center' }}>
            <LoadingSpinner label="Loading database benchmark catalog..." size="lg" />
          </div>
        ) : activeTab === 'history' ? (
          /* Execution History View */
          <div className="card" style={{ padding: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h2 style={{ fontSize: '1.125rem', fontWeight: 600, margin: 0 }}>Recent Lab Benchmark Runs</h2>
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={refreshHistory}
                disabled={isLoadingHistory}
              >
                <RotateCcw style={{ width: 14, height: 14 }} />
                Refresh
              </button>
            </div>

            {history.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '3rem 0', color: 'var(--color-text-secondary)' }}>
                No prior benchmark runs recorded yet. Execute a benchmark from the workspace to generate history.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--color-border)', color: 'var(--color-text-muted)' }}>
                      <th style={{ padding: '0.75rem' }}>Timestamp</th>
                      <th style={{ padding: '0.75rem' }}>Scenario</th>
                      <th style={{ padding: '0.75rem' }}>Dataset</th>
                      <th style={{ padding: '0.75rem' }}>No-Index Median</th>
                      <th style={{ padding: '0.75rem' }}>Indexed Median</th>
                      <th style={{ padding: '0.75rem' }}>Speedup</th>
                      <th style={{ padding: '0.75rem' }}>Status</th>
                      <th style={{ padding: '0.75rem' }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h) => (
                      <tr key={h.run_id} style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
                        <td style={{ padding: '0.75rem', color: 'var(--color-text-secondary)' }}>
                          {new Date(h.created_at).toLocaleString()}
                        </td>
                        <td style={{ padding: '0.75rem', fontWeight: 600 }}>{h.scenario_code}</td>
                        <td style={{ padding: '0.75rem' }}>
                          <span style={{ textTransform: 'capitalize', padding: '0.2rem 0.5rem', background: 'var(--color-surface-2)', borderRadius: '4px', fontSize: '0.75rem' }}>
                            {h.dataset_size}
                          </span>
                        </td>
                        <td style={{ padding: '0.75rem', fontFamily: 'monospace' }}>
                          {h.no_index_median_ms != null ? `${h.no_index_median_ms.toFixed(3)} ms` : '—'}
                        </td>
                        <td style={{ padding: '0.75rem', fontFamily: 'monospace' }}>
                          {h.indexed_median_ms != null ? `${h.indexed_median_ms.toFixed(3)} ms` : '—'}
                        </td>
                        <td style={{ padding: '0.75rem', fontWeight: 700, color: (h.speedup_ratio || 1) >= 1.5 ? 'var(--color-success)' : 'inherit' }}>
                          {h.speedup_ratio != null ? `${h.speedup_ratio.toFixed(2)}x` : '—'}
                        </td>
                        <td style={{ padding: '0.75rem' }}>
                          <span style={{
                            padding: '0.2rem 0.5rem',
                            borderRadius: '4px',
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            background: h.status === 'SUCCEEDED' ? 'var(--color-success-bg)' : 'var(--color-error-bg)',
                            color: h.status === 'SUCCEEDED' ? 'var(--color-success)' : 'var(--color-error)',
                          }}>
                            {h.status}
                          </span>
                        </td>
                        <td style={{ padding: '0.75rem' }}>
                          <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            onClick={() => handleLoadHistoryDetail(h.run_id)}
                          >
                            Inspect Plan
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ) : (
          /* Benchmark Workspace View */
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1fr) 2fr', gap: '1.5rem', alignItems: 'start' }}>
            {/* Left Column: Configuration & Controls */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              <div className="card" style={{ padding: '1.25rem' }}>
                <h2 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <Layers style={{ width: 18, height: 18, color: 'var(--color-accent)' }} />
                  Benchmark Scenario
                </h2>

                <form onSubmit={handleExecute} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  {/* Scenario selection */}
                  <div>
                    <label htmlFor="scenario-select" style={{ display: 'block', fontSize: '0.875rem', fontWeight: 500, marginBottom: '0.375rem' }}>
                      Approved Query Scenario
                    </label>
                    <select
                      id="scenario-select"
                      className="input"
                      value={selectedScenarioId}
                      onChange={(e) => setSelectedScenarioId(e.target.value)}
                      disabled={isExecuting}
                      style={{ width: '100%', padding: '0.5rem', borderRadius: '0.375rem', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', color: 'inherit' }}
                    >
                      {catalog?.scenarios.map((s) => (
                        <option key={s.scenario_id} value={s.scenario_id}>
                          {s.title}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Dataset scale selection */}
                  <div>
                    <label htmlFor="dataset-size-select" style={{ display: 'block', fontSize: '0.875rem', fontWeight: 500, marginBottom: '0.375rem' }}>
                      Dataset Scale in examos_lab
                    </label>
                    <select
                      id="dataset-size-select"
                      className="input"
                      value={selectedSize}
                      onChange={(e) => setSelectedSize(e.target.value)}
                      disabled={isExecuting}
                      style={{ width: '100%', padding: '0.5rem', borderRadius: '0.375rem', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', color: 'inherit' }}
                    >
                      {catalog?.dataset_sizes.map((d) => (
                        <option key={d.size_key} value={d.size_key}>
                          {d.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Seed and Repetitions */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                    <div>
                      <label htmlFor="seed-input" style={{ display: 'block', fontSize: '0.875rem', fontWeight: 500, marginBottom: '0.375rem' }}>
                        Seed (Reproducibility)
                      </label>
                      <input
                        id="seed-input"
                        type="number"
                        className="input"
                        value={seed}
                        onChange={(e) => setSeed(Number(e.target.value))}
                        disabled={isExecuting}
                        style={{ width: '100%', padding: '0.5rem', borderRadius: '0.375rem', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', color: 'inherit' }}
                      />
                    </div>
                    <div>
                      <label htmlFor="repetitions-input" style={{ display: 'block', fontSize: '0.875rem', fontWeight: 500, marginBottom: '0.375rem' }}>
                        Repetitions (1–10)
                      </label>
                      <input
                        id="repetitions-input"
                        type="number"
                        min={1}
                        max={10}
                        className="input"
                        value={repetitions}
                        onChange={(e) => setRepetitions(Number(e.target.value))}
                        disabled={isExecuting}
                        style={{ width: '100%', padding: '0.5rem', borderRadius: '0.375rem', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', color: 'inherit' }}
                      />
                    </div>
                  </div>

                  {/* Run Action */}
                  <button
                    type="submit"
                    className="btn btn--primary"
                    disabled={isExecuting}
                    style={{ width: '100%', marginTop: '0.5rem', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '0.5rem' }}
                  >
                    {isExecuting ? (
                      <>
                        <LoadingSpinner label="Running EXPLAIN ANALYZE..." size="sm" />
                        Measuring PostgreSQL Execution...
                      </>
                    ) : (
                      <>
                        <Play style={{ width: 16, height: 16 }} />
                        Execute Benchmark
                      </>
                    )}
                  </button>
                </form>
              </div>

              {/* Scenario Learning Goal & Information */}
              {currentScenario && (
                <div className="card" style={{ padding: '1.25rem', fontSize: '0.875rem' }}>
                  <h3 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                    <Info style={{ width: 16, height: 16, color: '#38bdf8' }} />
                    Learning Objective
                  </h3>
                  <p style={{ color: 'var(--color-text-secondary)', marginBottom: '0.75rem', lineHeight: 1.5 }}>
                    {currentScenario.learning_objective}
                  </p>

                  <h4 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: '0.25rem', color: 'var(--color-text)' }}>
                    Why Indexes Matter Here
                  </h4>
                  <p style={{ color: 'var(--color-text-secondary)', marginBottom: '0.75rem', lineHeight: 1.5 }}>
                    {currentScenario.index_explanation}
                  </p>

                  <div style={{ padding: '0.75rem', borderRadius: '0.375rem', background: 'rgba(251, 191, 36, 0.1)', border: '1px solid rgba(251, 191, 36, 0.25)', color: '#fbbf24' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', fontWeight: 600, marginBottom: '0.25rem' }}>
                      <AlertTriangle style={{ width: 14, height: 14 }} />
                      Educational Caveat
                    </div>
                    <div style={{ fontSize: '0.8125rem', lineHeight: 1.4 }}>
                      {currentScenario.caveat_notes}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Right Column: Benchmark Results & Plans */}
            <div>
              {activeResult ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                  {/* Results Summary Card */}
                  <div className="card" style={{ padding: '1.5rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.25rem' }}>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0 }}>
                            {activeResult.scenario_id}
                          </h2>
                          <span style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem', borderRadius: '4px', background: 'var(--color-surface-2)', textTransform: 'capitalize' }}>
                            Scale: {activeResult.dataset_size}
                          </span>
                        </div>
                        <div style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
                          PostgreSQL Engine: {activeResult.postgres_version.split(' ')[0]} {activeResult.postgres_version.split(' ')[1]} | {activeResult.repetitions} Repetitions (Median Reported)
                        </div>
                      </div>

                      {/* Speedup Badge */}
                      <div style={{
                        padding: '0.5rem 1rem',
                        borderRadius: '0.5rem',
                        background: activeResult.speedup_ratio >= 1.5 ? 'rgba(52, 211, 153, 0.15)' : 'rgba(99, 102, 241, 0.15)',
                        border: `1px solid ${activeResult.speedup_ratio >= 1.5 ? 'rgba(52, 211, 153, 0.3)' : 'rgba(99, 102, 241, 0.3)'}`,
                        textAlign: 'right',
                      }}>
                        <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                          Index Speedup
                        </div>
                        <div style={{ fontSize: '1.5rem', fontWeight: 800, color: activeResult.speedup_ratio >= 1.5 ? 'var(--color-success)' : 'var(--color-accent-light)' }}>
                          {activeResult.speedup_ratio.toFixed(2)}x
                        </div>
                      </div>
                    </div>

                    {/* Side-by-Side Metric Comparison */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.25rem' }}>
                      {/* Without Index */}
                      <div style={{
                        padding: '1rem',
                        borderRadius: '0.5rem',
                        background: 'rgba(239, 68, 68, 0.05)',
                        border: '1px solid rgba(239, 68, 68, 0.2)',
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                          <span style={{ fontWeight: 600, fontSize: '0.95rem', color: '#f87171' }}>
                            Without Index (Seq Scan)
                          </span>
                          <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                            Table: lab_*_no_index
                          </span>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', fontSize: '0.875rem' }}>
                          <div>
                            <div style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>Median Exec Time</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 700, fontFamily: 'monospace' }}>
                              {activeResult.no_index.median_time_ms.toFixed(3)} ms
                            </div>
                          </div>
                          <div>
                            <div style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>Planning Time</div>
                            <div style={{ fontSize: '1rem', fontFamily: 'monospace' }}>
                              {activeResult.no_index.planning_time_ms.toFixed(3)} ms
                            </div>
                          </div>
                          <div>
                            <div style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>Rows Scanned</div>
                            <div style={{ fontSize: '1rem', fontWeight: 600 }}>
                              {activeResult.no_index.row_count}
                            </div>
                          </div>
                          <div>
                            <div style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>Plan Node Type</div>
                            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#fca5a5' }}>
                              {activeResult.no_index.plan?.Plan?.['Node Type'] || 'Seq Scan'}
                            </div>
                          </div>
                        </div>

                        {/* Repetition Times */}
                        <div style={{ marginTop: '0.75rem', paddingTop: '0.5rem', borderTop: '1px solid rgba(239, 68, 68, 0.15)', fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                          Runs: {activeResult.no_index.repetition_times_ms.map((t) => `${t}ms`).join(', ')}
                        </div>
                      </div>

                      {/* With Index */}
                      <div style={{
                        padding: '1rem',
                        borderRadius: '0.5rem',
                        background: 'rgba(52, 211, 153, 0.05)',
                        border: '1px solid rgba(52, 211, 153, 0.2)',
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                          <span style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--color-success)' }}>
                            With Index (B-Tree Scan)
                          </span>
                          <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                            Table: lab_*_indexed
                          </span>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', fontSize: '0.875rem' }}>
                          <div>
                            <div style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>Median Exec Time</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 700, fontFamily: 'monospace', color: 'var(--color-success)' }}>
                              {activeResult.indexed.median_time_ms.toFixed(3)} ms
                            </div>
                          </div>
                          <div>
                            <div style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>Planning Time</div>
                            <div style={{ fontSize: '1rem', fontFamily: 'monospace' }}>
                              {activeResult.indexed.planning_time_ms.toFixed(3)} ms
                            </div>
                          </div>
                          <div>
                            <div style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>Rows Scanned</div>
                            <div style={{ fontSize: '1rem', fontWeight: 600 }}>
                              {activeResult.indexed.row_count}
                            </div>
                          </div>
                          <div>
                            <div style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>Plan Node Type</div>
                            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#6ee7b7' }}>
                              {activeResult.indexed.plan?.Plan?.['Node Type'] || 'Index Scan'}
                            </div>
                          </div>
                        </div>

                        {/* Repetition Times */}
                        <div style={{ marginTop: '0.75rem', paddingTop: '0.5rem', borderTop: '1px solid rgba(52, 211, 153, 0.15)', fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                          Runs: {activeResult.indexed.repetition_times_ms.map((t) => `${t}ms`).join(', ')}
                        </div>
                      </div>
                    </div>

                    {/* Educational Note */}
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', fontSize: '0.8125rem', color: 'var(--color-text-muted)', borderTop: '1px solid var(--color-border)', paddingTop: '0.75rem' }}>
                      <Clock style={{ width: 14, height: 14, marginTop: 2, flexShrink: 0 }} />
                      <div>
                        <strong>Real Measurement Notice:</strong> Timings reflect actual PostgreSQL EXPLAIN (ANALYZE, BUFFERS) internal measurements. Cache warmup, OS memory buffers, and system background load naturally cause variations across repetitions.
                      </div>
                    </div>
                  </div>

                  {/* Plan Inspection Card */}
                  <div className="card" style={{ padding: '1.5rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                      <h3 style={{ fontSize: '1.125rem', fontWeight: 600, margin: 0 }}>
                        PostgreSQL Execution Plan Inspection
                      </h3>
                      <div style={{ display: 'flex', gap: '0.375rem' }}>
                        <button
                          type="button"
                          className={`btn btn--sm ${viewingPlanVariant === 'both' ? 'btn--primary' : 'btn--ghost'}`}
                          onClick={() => setViewingPlanVariant('both')}
                        >
                          Side-by-Side
                        </button>
                        <button
                          type="button"
                          className={`btn btn--sm ${viewingPlanVariant === 'no_index' ? 'btn--primary' : 'btn--ghost'}`}
                          onClick={() => setViewingPlanVariant('no_index')}
                        >
                          No Index Plan
                        </button>
                        <button
                          type="button"
                          className={`btn btn--sm ${viewingPlanVariant === 'indexed' ? 'btn--primary' : 'btn--ghost'}`}
                          onClick={() => setViewingPlanVariant('indexed')}
                        >
                          Indexed Plan
                        </button>
                      </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: viewingPlanVariant === 'both' ? '1fr 1fr' : '1fr', gap: '1rem' }}>
                      {/* No Index Plan JSON */}
                      {(viewingPlanVariant === 'both' || viewingPlanVariant === 'no_index') && (
                        <div>
                          <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#f87171', marginBottom: '0.5rem' }}>
                            Sequential Scan Plan Tree (No Index)
                          </div>
                          <pre style={{
                            padding: '1rem',
                            borderRadius: '0.5rem',
                            background: '#090d16',
                            border: '1px solid var(--color-border)',
                            fontSize: '0.75rem',
                            color: '#94a3b8',
                            overflow: 'auto',
                            maxHeight: '400px',
                            fontFamily: 'Consolas, Monaco, monospace',
                          }}>
                            {JSON.stringify(activeResult.no_index.plan, null, 2)}
                          </pre>
                        </div>
                      )}

                      {/* Indexed Plan JSON */}
                      {(viewingPlanVariant === 'both' || viewingPlanVariant === 'indexed') && (
                        <div>
                          <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--color-success)', marginBottom: '0.5rem' }}>
                            Index Scan Plan Tree (Indexed)
                          </div>
                          <pre style={{
                            padding: '1rem',
                            borderRadius: '0.5rem',
                            background: '#090d16',
                            border: '1px solid var(--color-border)',
                            fontSize: '0.75rem',
                            color: '#94a3b8',
                            overflow: 'auto',
                            maxHeight: '400px',
                            fontFamily: 'Consolas, Monaco, monospace',
                          }}>
                            {JSON.stringify(activeResult.indexed.plan, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                /* Empty state when no run has happened yet */
                <div className="card" style={{ padding: '4rem 2rem', textAlign: 'center' }}>
                  <div style={{ width: 48, height: 48, margin: '0 auto 1rem', padding: '0.75rem', background: 'rgba(99, 102, 241, 0.1)', borderRadius: '50%', color: 'var(--color-accent)' }}>
                    <Play style={{ width: 24, height: 24 }} />
                  </div>
                  <h3 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '0.5rem' }}>
                    Ready to Execute Benchmark
                  </h3>
                  <p style={{ maxWidth: '480px', margin: '0 auto 1.5rem', fontSize: '0.875rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                    Select a predefined scenario and dataset scale on the left, then click <strong>Execute Benchmark</strong>. PostgreSQL will measure actual query plans and execution timings on isolated lab data.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
