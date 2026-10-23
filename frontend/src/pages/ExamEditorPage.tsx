/**
 * Faculty Exam Editor and Publishing Page — /faculty/exams/:examId (M1-EXAM-UI-1).
 *
 * Responsibilities:
 * - Loads exam details via GET /api/v1/exams/{exam_id}.
 * - For DRAFT exams:
 *     - Edit title, instructions, and duration (PATCH /api/v1/exams/{id}).
 *     - Add questions from question bank (POST /api/v1/exams/{id}/questions).
 *     - Reorder questions up/down or change marks (PUT /api/v1/exams/{id}/questions).
 *     - Remove question from draft (DELETE /api/v1/exams/{id}/questions/{qid}).
 *     - Publish review modal with confirmation (POST /api/v1/exams/{id}/publish).
 * - For PUBLISHED / UNPUBLISHED exams:
 *     - Renders frozen immutable snapshot view with options and marks.
 *     - Disables draft editing controls.
 *     - Supports Unpublish if exam is published (POST /api/v1/exams/{id}/unpublish).
 * - Clear error states, optimistic updates with server confirmation, loading spinners.
 */

import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  AlertCircle,
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  BookOpen,
  CheckCircle2,
  FileQuestion,
  Lock,
  Plus,
  Send,
  Trash2,
  X,
} from 'lucide-react';
import {
  apiAttachQuestionToExam,
  apiGetExam,
  apiGetQuestions,
  apiPublishExam,
  apiRemoveQuestionFromExam,
  apiSetExamQuestions,
  apiUnpublishExam,
  apiUpdateExam,
  type ExamDetailRead,
  type ExamDraftQuestionRead,
  type ExamQuestionSnapshotRead,
  type QuestionRead,
} from '../api/faculty';
import { useAuth } from '../contexts/AuthContext';
import { LoadingSpinner } from '../components/ui';

export function ExamEditorPage() {
  const { examId } = useParams<{ examId: string }>();
  const { csrfToken } = useAuth();
  const navigate = useNavigate();

  const [exam, setExam] = useState<ExamDetailRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);

  // Metadata Editing
  const [isEditingMeta, setIsEditingMeta] = useState(false);
  const [titleInput, setTitleInput] = useState('');
  const [instructionsInput, setInstructionsInput] = useState('');
  const [durationInput, setDurationInput] = useState('60');
  const [isSavingMeta, setIsSavingMeta] = useState(false);

  // Question Selector Modal
  const [isAttachModalOpen, setIsAttachModalOpen] = useState(false);
  const [availableQuestions, setAvailableQuestions] = useState<QuestionRead[]>([]);
  const [isLoadingQuestions, setIsLoadingQuestions] = useState(false);
  const [selectedQuestionId, setSelectedQuestionId] = useState('');
  const [marksInput, setMarksInput] = useState('1.00');
  const [attachError, setAttachError] = useState<string | null>(null);
  const [isAttaching, setIsAttaching] = useState(false);

  // Publish Confirmation Modal
  const [isPublishModalOpen, setIsPublishModalOpen] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  // Unpublish Confirmation Modal
  const [isUnpublishModalOpen, setIsUnpublishModalOpen] = useState(false);
  const [isUnpublishing, setIsUnpublishing] = useState(false);
  const [unpublishError, setUnpublishError] = useState<string | null>(null);

  // -------------------------------------------------------------------------
  // Data Loading
  // -------------------------------------------------------------------------
  const loadExam = useCallback(async () => {
    if (!examId) return;
    setIsLoading(true);
    setPageError(null);
    try {
      const data = await apiGetExam(examId);
      setExam(data);
      setTitleInput(data.title);
      setInstructionsInput(data.instructions);
      setDurationInput(String(data.duration_minutes));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load examination.';
      setPageError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [examId]);

  useEffect(() => {
    loadExam();
  }, [loadExam]);

  // -------------------------------------------------------------------------
  // Metadata Save
  // -------------------------------------------------------------------------
  async function handleSaveMetadata(e: React.FormEvent) {
    e.preventDefault();
    if (!exam) return;
    setPageError(null);

    const dur = parseInt(durationInput, 10);
    if (isNaN(dur) || dur < 1 || dur > 240) {
      setPageError('Duration must be between 1 and 240 minutes.');
      return;
    }

    setIsSavingMeta(true);
    try {
      await apiUpdateExam(
        exam.id,
        {
          title: titleInput.trim(),
          instructions: instructionsInput.trim(),
          duration_minutes: dur,
        },
        csrfToken,
      );
      setIsEditingMeta(false);
      await loadExam();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to update metadata.';
      setPageError(msg);
    } finally {
      setIsSavingMeta(false);
    }
  }

  // -------------------------------------------------------------------------
  // Attach Question
  // -------------------------------------------------------------------------
  async function openAttachModal() {
    setIsAttachModalOpen(true);
    setSelectedQuestionId('');
    setMarksInput('1.00');
    setAttachError(null);
    setIsLoadingQuestions(true);

    try {
      const allQ = await apiGetQuestions({ include_archived: false });
      // Filter out questions already in exam
      const existingQIds = new Set(
        (exam?.questions ?? []).map((q) => q.source_question_id).filter(Boolean),
      );
      const filtered = allQ.filter((q) => !existingQIds.has(q.id));
      setAvailableQuestions(filtered);
      if (filtered.length > 0) {
        setSelectedQuestionId(filtered[0].id);
      }
    } catch {
      setAttachError('Failed to load questions from question bank.');
    } finally {
      setIsLoadingQuestions(false);
    }
  }

  async function handleAttachQuestion(e: React.FormEvent) {
    e.preventDefault();
    if (!exam || !selectedQuestionId) return;

    const marksNum = parseFloat(marksInput);
    if (isNaN(marksNum) || marksNum <= 0) {
      setAttachError('Marks must be a positive number.');
      return;
    }

    setIsAttaching(true);
    setAttachError(null);

    try {
      await apiAttachQuestionToExam(
        exam.id,
        {
          question_id: selectedQuestionId,
          marks: marksNum,
        },
        csrfToken,
      );
      setIsAttachModalOpen(false);
      await loadExam();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to attach question.';
      setAttachError(msg);
    } finally {
      setIsAttaching(false);
    }
  }

  // -------------------------------------------------------------------------
  // Reorder & Remove Questions
  // -------------------------------------------------------------------------
  async function handleMoveQuestion(index: number, direction: 'up' | 'down') {
    if (!exam || exam.status !== 'DRAFT') return;
    const questions = [...(exam.questions as ExamDraftQuestionRead[])];
    const targetIndex = direction === 'up' ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= questions.length) return;

    // Swap positions
    const temp = questions[index];
    questions[index] = questions[targetIndex];
    questions[targetIndex] = temp;

    const payload = questions.map((q, idx) => ({
      question_id: q.source_question_id || q.id,
      marks: Number(q.marks),
      display_order: idx + 1,
    }));

    try {
      const updated = await apiSetExamQuestions(exam.id, payload, csrfToken);
      setExam(updated);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to reorder questions.';
      setPageError(msg);
    }
  }

  async function handleRemoveQuestion(questionId: string) {
    if (!exam || exam.status !== 'DRAFT') return;
    try {
      const updated = await apiRemoveQuestionFromExam(exam.id, questionId, csrfToken);
      setExam(updated);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to remove question.';
      setPageError(msg);
    }
  }

  // -------------------------------------------------------------------------
  // Publish / Unpublish
  // -------------------------------------------------------------------------
  async function handleConfirmPublish() {
    if (!exam) return;
    setIsPublishing(true);
    setPublishError(null);

    try {
      await apiPublishExam(exam.id, csrfToken);
      setIsPublishModalOpen(false);
      await loadExam();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Publication failed.';
      setPublishError(msg);
    } finally {
      setIsPublishing(false);
    }
  }

  async function handleConfirmUnpublish() {
    if (!exam) return;
    setIsUnpublishing(true);
    setUnpublishError(null);

    try {
      await apiUnpublishExam(exam.id, csrfToken);
      setIsUnpublishModalOpen(false);
      await loadExam();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unpublish failed.';
      setUnpublishError(msg);
    } finally {
      setIsUnpublishing(false);
    }
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  if (isLoading) {
    return (
      <div className="page-shell" aria-busy="true">
        <LoadingSpinner label="Loading examination..." size="lg" />
        <p className="text-secondary" style={{ marginTop: '1rem' }}>
          Loading examination details...
        </p>
      </div>
    );
  }

  if (pageError && !exam) {
    return (
      <div className="page-shell">
        <div className="auth-card">
          <AlertCircle className="text-error" size={32} style={{ marginBottom: '1rem' }} />
          <h1 className="auth-card__title">Unable to Open Examination</h1>
          <p className="text-secondary" style={{ marginBottom: '1.5rem' }}>
            {pageError}
          </p>
          <button
            type="button"
            className="btn btn--primary btn--full"
            onClick={() => navigate('/faculty/exams')}
          >
            Back to Examinations
          </button>
        </div>
      </div>
    );
  }

  if (!exam) return null;

  const isDraft = exam.status === 'DRAFT';
  const isPublished = exam.status === 'PUBLISHED';
  const questions = exam.questions ?? [];

  return (
    <div className="app-shell">
      <header className="app-header" role="banner">
        <div className="app-header__brand">
          <BookOpen className="app-header__logo-icon" aria-hidden="true" />
          <Link to="/faculty/exams" className="app-header__logo-text text-accent" style={{ textDecoration: 'none' }}>
            ExamOS
          </Link>
          <span className="text-secondary" style={{ margin: '0 0.5rem' }}>/</span>
          <span className="text-secondary font-medium">Exam Editor</span>
        </div>
        <div className="app-header__user">
          <Link to="/faculty/exams" className="btn btn--ghost btn--sm">
            <ArrowLeft className="btn__icon" aria-hidden="true" /> All Exams
          </Link>
        </div>
      </header>

      <main className="app-main" id="main-content">
        {pageError && (
          <div className="inline-error" style={{ marginBottom: '1.5rem' }} role="alert">
            <AlertCircle className="inline-error__icon" aria-hidden="true" />
            <div style={{ flex: 1 }}>
              <p style={{ margin: 0 }}>{pageError}</p>
            </div>
          </div>
        )}

        {/* Hero Card with Metadata */}
        <div className="results-hero-card">
          <div className="results-hero-card__header">
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                <span className="workspace-badge">
                  {isDraft ? 'DRAFT EXAMINATION' : isPublished ? 'PUBLISHED ASSESSMENT' : 'UNPUBLISHED'}
                </span>
                {!isDraft && (
                  <span className="exam-badge" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                    <Lock size={12} aria-hidden="true" /> Frozen Snapshot
                  </span>
                )}
              </div>
              <h1 className="results-hero-card__title">{exam.title}</h1>
              {exam.instructions && (
                <p className="text-secondary" style={{ margin: '0.25rem 0 0' }}>
                  {exam.instructions}
                </p>
              )}
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              {isDraft && (
                <>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => setIsEditingMeta(!isEditingMeta)}
                  >
                    {isEditingMeta ? 'Cancel Edit' : 'Edit Details'}
                  </button>
                  <button
                    type="button"
                    className="btn btn--primary"
                    onClick={() => {
                      setPublishError(null);
                      setIsPublishModalOpen(true);
                    }}
                    disabled={questions.length === 0}
                  >
                    <Send className="btn__icon" aria-hidden="true" /> Review & Publish
                  </button>
                </>
              )}
              {isPublished && (
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => {
                    setUnpublishError(null);
                    setIsUnpublishModalOpen(true);
                  }}
                  style={{ color: 'var(--color-warning)' }}
                >
                  Unpublish Exam
                </button>
              )}
            </div>
          </div>

          {/* Edit Metadata Form (if open) */}
          {isEditingMeta && isDraft && (
            <form onSubmit={handleSaveMetadata} style={{ padding: '1rem', background: 'var(--color-surface-2)', borderRadius: 'var(--radius-lg)', marginBottom: '1.5rem' }}>
              <h2 style={{ fontSize: '1rem', fontWeight: 600, margin: '0 0 1rem 0' }}>Edit Exam Details</h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(15rem, 1fr))', gap: '1rem', marginBottom: '1rem' }}>
                <div className="form-field">
                  <label htmlFor="edit-title" className="form-label">Title *</label>
                  <input
                    id="edit-title"
                    type="text"
                    value={titleInput}
                    onChange={(e) => setTitleInput(e.target.value)}
                    className="form-input"
                    required
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="edit-duration" className="form-label">Duration (Minutes, 1-240) *</label>
                  <input
                    id="edit-duration"
                    type="number"
                    min={1}
                    max={240}
                    value={durationInput}
                    onChange={(e) => setDurationInput(e.target.value)}
                    className="form-input"
                    required
                  />
                </div>
              </div>
              <div className="form-field" style={{ marginBottom: '1rem' }}>
                <label htmlFor="edit-instructions" className="form-label">Instructions</label>
                <textarea
                  id="edit-instructions"
                  value={instructionsInput}
                  onChange={(e) => setInstructionsInput(e.target.value)}
                  className="form-input"
                  rows={2}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => setIsEditingMeta(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn--primary btn--sm" disabled={isSavingMeta}>
                  {isSavingMeta ? <LoadingSpinner size="sm" /> : 'Save Details'}
                </button>
              </div>
            </form>
          )}

          {/* Metrics Bar */}
          <div className="results-metrics-grid">
            <div className="results-metric">
              <span className="results-metric__label">Questions</span>
              <span className="results-metric__val text-text">{questions.length}</span>
            </div>
            <div className="results-metric">
              <span className="results-metric__label">Total Marks</span>
              <span className="results-metric__val text-success">{Number(exam.total_marks).toFixed(2)}</span>
            </div>
            <div className="results-metric">
              <span className="results-metric__label">Duration</span>
              <span className="results-metric__val text-accent">{exam.duration_minutes} mins</span>
            </div>
          </div>
        </div>

        {/* Question Management Section */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '2rem 0 1rem' }}>
          <div>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0 }}>
              {isDraft ? 'Draft Questions' : 'Frozen Assessment Questions'}
            </h2>
            <p className="text-secondary" style={{ fontSize: '0.875rem', margin: '0.25rem 0 0' }}>
              {isDraft
                ? 'Attach, reorder, and configure marks for questions in this draft.'
                : 'Questions and options are locked into an immutable snapshot and cannot be modified.'}
            </p>
          </div>

          {isDraft && (
            <button
              type="button"
              className="btn btn--primary"
              onClick={openAttachModal}
            >
              <Plus className="btn__icon" aria-hidden="true" /> Attach Question
            </button>
          )}
        </div>

        {questions.length === 0 ? (
          <div className="exam-card exam-card--empty">
            <FileQuestion className="exam-card__empty-icon" aria-hidden="true" />
            <h3 className="exam-card__empty-title">No questions attached</h3>
            <p className="text-secondary">
              Attach questions from the question bank to populate this draft examination.
            </p>
            {isDraft && (
              <button
                type="button"
                className="btn btn--primary"
                style={{ marginTop: '1rem' }}
                onClick={openAttachModal}
              >
                <Plus className="btn__icon" aria-hidden="true" /> Attach Question
              </button>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {questions.map((q, idx) => {
              const snapshotQ = q as ExamQuestionSnapshotRead;
              const draftQ = q as ExamDraftQuestionRead;
              const topicLabel = snapshotQ.topic_name_snapshot || draftQ.topic_name;

              return (
                <article
                  key={q.id}
                  className="exam-card"
                  style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <span className="result-q-number" style={{ background: 'var(--color-surface-2)', padding: '0.25rem 0.5rem', borderRadius: 'var(--radius-sm)' }}>
                        #{idx + 1}
                      </span>
                      <span className="text-secondary" style={{ fontSize: '0.875rem' }}>
                        {Number(q.marks).toFixed(1)} marks
                      </span>
                      {topicLabel && (
                        <span className="exam-badge" style={{ fontSize: '0.75rem' }}>
                          {topicLabel}
                        </span>
                      )}
                    </div>

                    {isDraft && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <button
                          type="button"
                          className="btn-icon"
                          onClick={() => handleMoveQuestion(idx, 'up')}
                          disabled={idx === 0}
                          title="Move up"
                          aria-label="Move question up"
                        >
                          <ArrowUp size={16} />
                        </button>
                        <button
                          type="button"
                          className="btn-icon"
                          onClick={() => handleMoveQuestion(idx, 'down')}
                          disabled={idx === questions.length - 1}
                          title="Move down"
                          aria-label="Move question down"
                        >
                          <ArrowDown size={16} />
                        </button>
                        <button
                          type="button"
                          className="btn-icon"
                          onClick={() => handleRemoveQuestion(draftQ.source_question_id || draftQ.id)}
                          title="Remove from draft"
                          aria-label="Remove question from draft"
                          style={{ color: 'var(--color-error)' }}
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    )}
                  </div>

                  <p style={{ margin: 0, fontSize: '1rem', fontWeight: 500, color: 'var(--color-text)' }}>
                    {snapshotQ.prompt_snapshot || draftQ.prompt}
                  </p>

                  {/* Render Options for published snapshots */}
                  {snapshotQ.options && snapshotQ.options.length > 0 && (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(16rem, 1fr))', gap: '0.5rem', marginTop: '0.25rem' }}>
                      {snapshotQ.options.map((opt) => (
                        <div
                          key={opt.id}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            padding: '0.35rem 0.6rem',
                            background: opt.is_correct ? 'rgba(52, 211, 153, 0.1)' : 'var(--color-surface-2)',
                            border: `1px solid ${opt.is_correct ? 'rgba(52, 211, 153, 0.3)' : 'var(--color-border-subtle)'}`,
                            borderRadius: 'var(--radius-sm)',
                            fontSize: '0.8125rem',
                          }}
                        >
                          {opt.is_correct ? (
                            <CheckCircle2 size={14} className="text-success" aria-hidden="true" />
                          ) : (
                            <span style={{ width: '14px', height: '14px', borderRadius: '50%', border: '1px solid var(--color-border)', display: 'inline-block' }} />
                          )}
                          <span style={{ color: opt.is_correct ? 'var(--color-success)' : 'var(--color-text)' }}>
                            {opt.option_text_snapshot}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </main>

      {/* Attach Question Modal */}
      {isAttachModalOpen && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="attach-title">
          <div className="modal-content" style={{ maxWidth: '36rem' }}>
            <div className="modal-header">
              <h2 id="attach-title" className="modal-title">
                Attach Question from Bank
              </h2>
              <button
                type="button"
                className="btn-icon"
                onClick={() => setIsAttachModalOpen(false)}
                disabled={isAttaching}
                aria-label="Close"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            <form onSubmit={handleAttachQuestion}>
              <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {attachError && (
                  <div className="inline-error" role="alert">
                    <AlertCircle className="inline-error__icon" aria-hidden="true" />
                    <span>{attachError}</span>
                  </div>
                )}

                {isLoadingQuestions ? (
                  <div style={{ textAlign: 'center', padding: '2rem' }}>
                    <LoadingSpinner label="Loading question bank..." />
                  </div>
                ) : availableQuestions.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--color-text-secondary)' }}>
                    All available questions from your question bank are already attached or archived.
                  </div>
                ) : (
                  <>
                    <div className="form-field">
                      <label htmlFor="select-q" className="form-label">
                        Select Question <span className="text-error">*</span>
                      </label>
                      <select
                        id="select-q"
                        value={selectedQuestionId}
                        onChange={(e) => setSelectedQuestionId(e.target.value)}
                        className="form-input"
                        required
                      >
                        {availableQuestions.map((q) => (
                          <option key={q.id} value={q.id}>
                            {q.topic ? `[${q.topic.code}] ` : ''}{q.prompt.length > 70 ? `${q.prompt.slice(0, 70)}...` : q.prompt}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="form-field">
                      <label htmlFor="q-marks" className="form-label">
                        Allocated Marks <span className="text-error">*</span>
                      </label>
                      <input
                        id="q-marks"
                        type="number"
                        step="0.5"
                        min="0.5"
                        max="100"
                        value={marksInput}
                        onChange={(e) => setMarksInput(e.target.value)}
                        className="form-input"
                        required
                      />
                    </div>
                  </>
                )}
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => setIsAttachModalOpen(false)}
                  disabled={isAttaching}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn--primary"
                  disabled={isAttaching || availableQuestions.length === 0}
                  aria-busy={isAttaching}
                >
                  {isAttaching ? <LoadingSpinner size="sm" /> : 'Attach to Draft'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Publish Review Modal */}
      {isPublishModalOpen && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="publish-title">
          <div className="modal-content" style={{ maxWidth: '32rem' }}>
            <div className="modal-header">
              <h2 id="publish-title" className="modal-title">
                Publish Examination?
              </h2>
              <button
                type="button"
                className="btn-icon"
                onClick={() => setIsPublishModalOpen(false)}
                disabled={isPublishing}
                aria-label="Close"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            <div className="modal-body">
              <p className="text-secondary" style={{ marginBottom: '1rem' }}>
                Publishing freezes this examination into an <strong>immutable assessment snapshot</strong>.
              </p>

              <div className="submit-stats-box" style={{ marginBottom: '1rem' }}>
                <div className="submit-stat">
                  <span className="submit-stat__num text-accent">{questions.length}</span>
                  <span className="submit-stat__label">Questions</span>
                </div>
                <div className="submit-stat">
                  <span className="submit-stat__num text-success">{Number(exam.total_marks).toFixed(1)}</span>
                  <span className="submit-stat__label">Total Marks</span>
                </div>
                <div className="submit-stat">
                  <span className="submit-stat__num text-text">{exam.duration_minutes}m</span>
                  <span className="submit-stat__label">Duration</span>
                </div>
              </div>

              <div className="inline-warning" style={{ marginBottom: '1rem' }}>
                <AlertTriangle size={16} aria-hidden="true" />
                <span>
                  Once published, questions and options cannot be edited. Students will immediately be able to take attempts.
                </span>
              </div>

              {publishError && (
                <div className="inline-error" role="alert">
                  <AlertCircle className="inline-error__icon" aria-hidden="true" />
                  <span>{publishError}</span>
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setIsPublishModalOpen(false)}
                disabled={isPublishing}
              >
                Keep as Draft
              </button>
              <button
                type="button"
                className="btn btn--primary"
                onClick={handleConfirmPublish}
                disabled={isPublishing}
                aria-busy={isPublishing}
              >
                {isPublishing ? <LoadingSpinner size="sm" /> : 'Confirm & Publish'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Unpublish Modal */}
      {isUnpublishModalOpen && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="unpublish-title">
          <div className="modal-content" style={{ maxWidth: '30rem' }}>
            <div className="modal-header">
              <h2 id="unpublish-title" className="modal-title">
                Unpublish Examination?
              </h2>
              <button
                type="button"
                className="btn-icon"
                onClick={() => setIsUnpublishModalOpen(false)}
                disabled={isUnpublishing}
                aria-label="Close"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            <div className="modal-body">
              <p className="text-secondary" style={{ marginBottom: '1rem' }}>
                Unpublishing this examination blocks students from starting new attempts. Existing submitted and in-progress attempts remain intact.
              </p>

              {unpublishError && (
                <div className="inline-error" role="alert">
                  <AlertCircle className="inline-error__icon" aria-hidden="true" />
                  <span>{unpublishError}</span>
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setIsUnpublishModalOpen(false)}
                disabled={isUnpublishing}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn--primary"
                onClick={handleConfirmUnpublish}
                disabled={isUnpublishing}
                aria-busy={isUnpublishing}
              >
                {isUnpublishing ? <LoadingSpinner size="sm" /> : 'Confirm Unpublish'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
