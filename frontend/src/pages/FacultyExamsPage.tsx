/**
 * Faculty Examinations List Page — /faculty/exams (M1-EXAM-UI-1).
 *
 * Responsibilities:
 * - Lists examinations created by faculty via GET /api/v1/exams.
 * - Displays status badges (DRAFT, PUBLISHED, UNPUBLISHED), duration, total questions, marks, and timestamps.
 * - Provides "New Examination" modal dialog for draft creation (title, instructions, duration).
 * - Provides navigation to /faculty/exams/:examId for draft editor and publishing.
 * - Supports Unpublish action for published exams if permitted.
 */

import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Clock,
  FileQuestion,
  HelpCircle,
  Plus,
  RotateCcw,
  X,
} from 'lucide-react';
import {
  apiCreateExam,
  apiGetExams,
  type ExamRead,
} from '../api/faculty';
import { useAuth } from '../contexts/AuthContext';
import { LoadingSpinner } from '../components/ui';

export function FacultyExamsPage() {
  const { csrfToken } = useAuth();
  const navigate = useNavigate();

  const [exams, setExams] = useState<ExamRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // New Exam Modal
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [instructions, setInstructions] = useState('');
  const [duration, setDuration] = useState('60');
  const [modalError, setModalError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const loadExams = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await apiGetExams();
      setExams(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load examinations.';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadExams();
  }, [loadExams]);

  async function handleCreateExam(e: React.FormEvent) {
    e.preventDefault();
    setModalError(null);

    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setModalError('Title is required.');
      return;
    }

    const durNum = parseInt(duration, 10);
    if (isNaN(durNum) || durNum < 1 || durNum > 240) {
      setModalError('Duration must be between 1 and 240 minutes.');
      return;
    }

    setIsCreating(true);
    try {
      const created = await apiCreateExam(
        {
          title: trimmedTitle,
          instructions: instructions.trim(),
          duration_minutes: durNum,
        },
        csrfToken,
      );
      setIsModalOpen(false);
      navigate(`/faculty/exams/${created.id}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to create examination.';
      setModalError(msg);
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header" role="banner">
        <div className="app-header__brand">
          <BookOpen className="app-header__logo-icon" aria-hidden="true" />
          <Link to="/dashboard" className="app-header__logo-text text-accent" style={{ textDecoration: 'none' }}>
            ExamOS
          </Link>
          <span className="text-secondary" style={{ margin: '0 0.5rem' }}>/</span>
          <span className="text-secondary font-medium">Faculty Examinations</span>
        </div>
        <div className="app-header__user">
          <Link to="/faculty/questions" className="btn btn--ghost btn--sm">
            Question Bank
          </Link>
          <Link to="/dashboard" className="btn btn--ghost btn--sm">
            Dashboard
          </Link>
        </div>
      </header>

      <main className="app-main" id="main-content">
        <div className="dashboard-hero" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h1 className="dashboard-hero__title">Examinations</h1>
            <p className="dashboard-hero__subtitle text-secondary">
              Author drafts, organize question selections, and atomically publish immutable exam snapshots.
            </p>
          </div>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => {
              setTitle('');
              setInstructions('');
              setDuration('60');
              setModalError(null);
              setIsModalOpen(true);
            }}
          >
            <Plus className="btn__icon" aria-hidden="true" /> New Examination
          </button>
        </div>

        {error && (
          <div className="inline-error" style={{ marginBottom: '1.5rem' }} role="alert">
            <AlertCircle className="inline-error__icon" aria-hidden="true" />
            <div style={{ flex: 1 }}>
              <p style={{ margin: '0 0 0.5rem 0' }}>{error}</p>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={loadExams}
              >
                <RotateCcw className="btn__icon" aria-hidden="true" /> Retry
              </button>
            </div>
          </div>
        )}

        {isLoading ? (
          <div style={{ textAlign: 'center', padding: '4rem 1rem' }} aria-busy="true">
            <LoadingSpinner label="Loading examinations…" size="lg" />
            <p className="text-secondary" style={{ marginTop: '1rem' }}>
              Fetching examination registry…
            </p>
          </div>
        ) : exams.length === 0 ? (
          <div className="exam-card exam-card--empty">
            <HelpCircle className="exam-card__empty-icon" aria-hidden="true" />
            <h2 className="exam-card__empty-title">No examinations yet</h2>
            <p className="text-secondary">
              Create a new examination draft to begin attaching questions and preparing assessments.
            </p>
            <button
              type="button"
              className="btn btn--primary"
              style={{ marginTop: '1rem' }}
              onClick={() => setIsModalOpen(true)}
            >
              <Plus className="btn__icon" aria-hidden="true" /> Create Examination
            </button>
          </div>
        ) : (
          <div className="exam-list" role="list">
            {exams.map((exam) => {
              const isDraft = exam.status === 'DRAFT';
              const isPublished = exam.status === 'PUBLISHED';
              const isUnpublished = exam.status === 'UNPUBLISHED';

              return (
                <article key={exam.id} className="exam-card" role="listitem">
                  <div className="exam-card__header">
                    <div className="exam-card__title-row">
                      <h2 className="exam-card__title">{exam.title}</h2>
                      {isDraft && (
                        <span className="exam-badge" style={{ background: 'rgba(99, 102, 241, 0.15)', color: 'var(--color-accent-light)' }}>
                          Draft
                        </span>
                      )}
                      {isPublished && (
                        <span className="exam-badge exam-badge--completed">
                          <CheckCircle2 size={13} aria-hidden="true" /> Published
                        </span>
                      )}
                      {isUnpublished && (
                        <span className="exam-badge" style={{ background: 'rgba(248, 113, 113, 0.15)', color: 'var(--color-error)' }}>
                          Unpublished
                        </span>
                      )}
                    </div>
                    {exam.instructions && (
                      <p className="exam-card__instructions text-secondary">
                        {exam.instructions}
                      </p>
                    )}
                  </div>

                  <div className="exam-card__meta-bar">
                    <div className="exam-meta-item">
                      <Clock size={16} className="text-muted" aria-hidden="true" />
                      <span>{exam.duration_minutes} mins</span>
                    </div>
                    <div className="exam-meta-item">
                      <FileQuestion size={16} className="text-muted" aria-hidden="true" />
                      <span>{exam.question_count} questions</span>
                    </div>
                    <div className="exam-meta-item">
                      <span className="text-muted font-medium">Marks:</span>
                      <span>{Number(exam.total_marks).toFixed(2)}</span>
                    </div>
                    <div className="exam-meta-item" style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                      Updated: {new Date(exam.updated_at).toLocaleDateString()}
                    </div>
                  </div>

                  <div className="exam-card__footer">
                    <Link
                      to={`/faculty/exams/${exam.id}`}
                      className="btn btn--primary"
                    >
                      {isDraft ? 'Open Draft Editor' : 'View Assessment Snapshot'} <ArrowRight className="btn__icon" aria-hidden="true" />
                    </Link>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </main>

      {/* New Exam Modal */}
      {isModalOpen && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="new-exam-title">
          <div className="modal-content" style={{ maxWidth: '32rem' }}>
            <div className="modal-header">
              <h2 id="new-exam-title" className="modal-title">
                Create Examination Draft
              </h2>
              <button
                type="button"
                className="btn-icon"
                onClick={() => setIsModalOpen(false)}
                disabled={isCreating}
                aria-label="Close"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            <form onSubmit={handleCreateExam}>
              <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {modalError && (
                  <div className="inline-error" role="alert">
                    <AlertCircle className="inline-error__icon" aria-hidden="true" />
                    <span>{modalError}</span>
                  </div>
                )}

                <div className="form-field">
                  <label htmlFor="exam-title" className="form-label">
                    Examination Title <span className="text-error">*</span>
                  </label>
                  <input
                    id="exam-title"
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="form-input"
                    placeholder="e.g. Operating Systems Midterm 2026"
                    required
                  />
                </div>

                <div className="form-field">
                  <label htmlFor="exam-duration" className="form-label">
                    Duration (Minutes, 1 to 240) <span className="text-error">*</span>
                  </label>
                  <input
                    id="exam-duration"
                    type="number"
                    min={1}
                    max={240}
                    value={duration}
                    onChange={(e) => setDuration(e.target.value)}
                    className="form-input"
                    required
                  />
                </div>

                <div className="form-field">
                  <label htmlFor="exam-instructions" className="form-label">
                    Student Instructions (Optional)
                  </label>
                  <textarea
                    id="exam-instructions"
                    value={instructions}
                    onChange={(e) => setInstructions(e.target.value)}
                    className="form-input"
                    rows={3}
                    placeholder="Instructions shown to students before starting..."
                  />
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => setIsModalOpen(false)}
                  disabled={isCreating}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn--primary"
                  disabled={isCreating}
                  aria-busy={isCreating}
                >
                  {isCreating ? <LoadingSpinner size="sm" /> : 'Create Draft'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
