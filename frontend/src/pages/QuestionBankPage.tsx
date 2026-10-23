/**
 * Question Bank Page — /faculty/questions (M1-EXAM-UI-1, M4-ML-UI-1).
 *
 * Responsibilities:
 * - List questions in question bank with authoring metadata, options count, topic badge, and archive status.
 * - Search by prompt text and filter by topic from GET /api/v1/topics.
 * - Create new question modal with 2-6 options, exactly one correct option, and display order.
 * - Edit existing question modal (only for active questions).
 * - Archive confirmation dialog modal (soft-archive via POST /api/v1/questions/{id}/archive).
 * - ML topic suggestion panel: explicit "Suggest Topic" action, Use/Dismiss flow (M4-ML-UI-1).
 * - Preserves CSRF, shows clear validation errors, loading, and empty states.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertCircle,
  Archive,
  BookOpen,
  CheckCircle2,
  Edit2,
  Filter,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import {
  apiArchiveQuestion,
  apiCreateQuestion,
  apiGetQuestions,
  apiGetTopics,
  apiUpdateQuestion,
  type QuestionCreate,
  type QuestionOptionCreate,
  type QuestionRead,
  type TopicRead,
} from '../api/faculty';
import {
  apiGetTopicSuggestion,
  type TopicSuggestionDetails,
} from '../api/ml';
import { useAuth } from '../contexts/AuthContext';
import { LoadingSpinner } from '../components/ui';

interface OptionDraft {
  text: string;
  is_correct: boolean;
}

export function QuestionBankPage() {
  const { user, csrfToken } = useAuth();

  const [questions, setQuestions] = useState<QuestionRead[]>([]);
  const [topics, setTopics] = useState<TopicRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [search, setSearch] = useState('');
  const [selectedTopicId, setSelectedTopicId] = useState('');
  const [includeArchived, setIncludeArchived] = useState(false);

  // Modal: Question Editor (Create / Edit)
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [editingQuestion, setEditingQuestion] = useState<QuestionRead | null>(null);
  const [promptInput, setPromptInput] = useState('');
  const [topicInput, setTopicInput] = useState('');
  const [optionsDraft, setOptionsDraft] = useState<OptionDraft[]>([
    { text: '', is_correct: true },
    { text: '', is_correct: false },
  ]);
  const [editorError, setEditorError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // ML Topic Suggestion state (M4-ML-UI-1)
  const [isSuggesting, setIsSuggesting] = useState(false);
  const [suggestionResult, setSuggestionResult] = useState<TopicSuggestionDetails | null>(null);
  const [suggestionUnavailableReason, setSuggestionUnavailableReason] = useState<string | null>(null);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);
  // Track last prompt+options snapshot sent so we can detect staleness
  const lastSuggestSnapshotRef = useRef<string>('');

  // Modal: Archive Confirmation
  const [archivingQuestion, setArchivingQuestion] = useState<QuestionRead | null>(null);
  const [isArchiving, setIsArchiving] = useState(false);
  const [archiveError, setArchiveError] = useState<string | null>(null);

  // -------------------------------------------------------------------------
  // Data Loading
  // -------------------------------------------------------------------------
  const loadTopics = useCallback(async () => {
    try {
      const data = await apiGetTopics();
      setTopics(data);
    } catch {
      // Topics failure non-fatal, can still list questions
    }
  }, []);

  const loadQuestions = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await apiGetQuestions({
        topic_id: selectedTopicId || undefined,
        search: search.trim() || undefined,
        include_archived: includeArchived,
      });
      setQuestions(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load question bank.';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [selectedTopicId, search, includeArchived]);

  useEffect(() => {
    loadTopics();
  }, [loadTopics]);

  useEffect(() => {
    loadQuestions();
  }, [loadQuestions]);

  // -------------------------------------------------------------------------
  // Editor Handlers
  // -------------------------------------------------------------------------

  /** Reset ML suggestion state — call whenever the editor opens, closes, or switches question. */
  function clearSuggestion() {
    setSuggestionResult(null);
    setSuggestionUnavailableReason(null);
    setSuggestionError(null);
    lastSuggestSnapshotRef.current = '';
  }

  function openCreateModal() {
    setEditingQuestion(null);
    setPromptInput('');
    setTopicInput('');
    setOptionsDraft([
      { text: '', is_correct: true },
      { text: '', is_correct: false },
    ]);
    setEditorError(null);
    clearSuggestion();
    setIsEditorOpen(true);
  }

  function openEditModal(q: QuestionRead) {
    setEditingQuestion(q);
    setPromptInput(q.prompt);
    setTopicInput(q.topic_id ?? '');
    setOptionsDraft(
      q.options.map((o) => ({
        text: o.option_text,
        is_correct: o.is_correct,
      })),
    );
    setEditorError(null);
    clearSuggestion();
    setIsEditorOpen(true);
  }

  /**
   * Request a topic suggestion from the ML service.
   * Uses the current promptInput and optionsDraft texts.
   * This is an explicit user action — never called automatically.
   */
  async function handleSuggestTopic() {
    const trimmedPrompt = promptInput.trim();
    if (!trimmedPrompt) {
      setSuggestionError('Enter a question prompt before requesting a topic suggestion.');
      return;
    }

    // Build snapshot key to detect if content has changed since last call
    const optionTexts = optionsDraft.map((o) => o.text.trim()).filter(Boolean);
    const snapshot = JSON.stringify({ prompt: trimmedPrompt, options: optionTexts });

    // Clear stale state first, THEN set the snapshot ref.
    // clearSuggestion() resets lastSuggestSnapshotRef to '', so the ref must
    // be written after the clear — otherwise the stale-content guard below
    // always sees '' !== snapshot and silently discards the API response.
    clearSuggestion();
    lastSuggestSnapshotRef.current = snapshot;
    setIsSuggesting(true);

    try {
      const response = await apiGetTopicSuggestion(
        { prompt: trimmedPrompt, options: optionTexts.length > 0 ? optionTexts : undefined },
        csrfToken,
      );

      // Discard result if the user changed content while the request was in flight
      if (lastSuggestSnapshotRef.current !== snapshot) return;

      if (response.available && response.suggestion) {
        setSuggestionResult(response.suggestion);
      } else {
        const reason = response.available === false ? response.reason : 'LOW_CONFIDENCE';
        setSuggestionUnavailableReason(reason);
      }
    } catch (err: unknown) {
      if (lastSuggestSnapshotRef.current !== snapshot) return;
      const msg = err instanceof Error ? err.message : 'Topic suggestion request failed.';
      setSuggestionError(msg);
    } finally {
      setIsSuggesting(false);
    }
  }

  /**
   * Apply the displayed suggestion to the topic selector.
   * Looks up the topic_code in the already-loaded topics list and sets topicInput
   * to the matching topic UUID. If the code is not found, shows a safe message.
   */
  function handleUseSuggestion() {
    if (!suggestionResult) return;
    const match = topics.find((t) => t.code === suggestionResult.topic_code);
    if (match) {
      setTopicInput(match.id);
      clearSuggestion();
    } else {
      setSuggestionError(
        `Suggested topic code "${suggestionResult.topic_code}" is not available in the current topic list. Please select a topic manually.`,
      );
      setSuggestionResult(null);
    }
  }

  function handleAddOption() {
    if (optionsDraft.length >= 6) {
      setEditorError('Questions can have at most 6 options.');
      return;
    }
    setEditorError(null);
    clearSuggestion();
    setOptionsDraft((prev) => [...prev, { text: '', is_correct: false }]);
  }

  function handleRemoveOption(index: number) {
    if (optionsDraft.length <= 2) {
      setEditorError('Questions must have at least 2 options.');
      return;
    }
    setEditorError(null);
    clearSuggestion();
    const wasCorrect = optionsDraft[index].is_correct;
    const next = optionsDraft.filter((_, idx) => idx !== index);
    if (wasCorrect && next.length > 0) {
      next[0].is_correct = true;
    }
    setOptionsDraft(next);
  }

  function handleSetCorrect(index: number) {
    setOptionsDraft((prev) =>
      prev.map((opt, idx) => ({
        ...opt,
        is_correct: idx === index,
      })),
    );
  }

  function handlePromptChange(val: string) {
    setPromptInput(val);
    clearSuggestion();
  }

  function handleOptionTextChange(index: number, val: string) {
    setOptionsDraft((prev) =>
      prev.map((opt, idx) => (idx === index ? { ...opt, text: val } : opt)),
    );
    clearSuggestion();
  }

  async function handleSaveQuestion(e: React.FormEvent) {
    e.preventDefault();
    setEditorError(null);

    const trimmedPrompt = promptInput.trim();
    if (!trimmedPrompt) {
      setEditorError('Question prompt cannot be empty.');
      return;
    }

    if (optionsDraft.length < 2 || optionsDraft.length > 6) {
      setEditorError('Questions must contain between 2 and 6 options.');
      return;
    }

    const hasEmptyOption = optionsDraft.some((o) => !o.text.trim());
    if (hasEmptyOption) {
      setEditorError('All option fields must have non-empty text.');
      return;
    }

    const correctCount = optionsDraft.filter((o) => o.is_correct).length;
    if (correctCount !== 1) {
      setEditorError('Please select exactly one correct option.');
      return;
    }

    setIsSaving(true);
    const payloadOptions: QuestionOptionCreate[] = optionsDraft.map((opt, idx) => ({
      text: opt.text.trim(),
      is_correct: opt.is_correct,
      display_order: idx + 1,
    }));

    try {
      if (editingQuestion) {
        await apiUpdateQuestion(
          editingQuestion.id,
          {
            prompt: trimmedPrompt,
            topic_id: topicInput || null,
            options: payloadOptions,
          },
          csrfToken,
        );
      } else {
        const payload: QuestionCreate = {
          prompt: trimmedPrompt,
          topic_id: topicInput || null,
          options: payloadOptions,
        };
        await apiCreateQuestion(payload, csrfToken);
      }

      setIsEditorOpen(false);
      await loadQuestions();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save question.';
      setEditorError(msg);
    } finally {
      setIsSaving(false);
    }
  }

  // -------------------------------------------------------------------------
  // Archive Handler
  // -------------------------------------------------------------------------
  async function handleConfirmArchive() {
    if (!archivingQuestion) return;
    setIsArchiving(true);
    setArchiveError(null);
    try {
      await apiArchiveQuestion(archivingQuestion.id, csrfToken);
      setArchivingQuestion(null);
      await loadQuestions();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to archive question.';
      setArchiveError(msg);
    } finally {
      setIsArchiving(false);
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
          <span className="text-secondary font-medium">Question Bank</span>
        </div>
        <div className="app-header__user">
          <Link to="/faculty/exams" className="btn btn--ghost btn--sm">
            Examinations
          </Link>
          <Link to="/dashboard" className="btn btn--ghost btn--sm">
            Dashboard
          </Link>
        </div>
      </header>

      <main className="app-main" id="main-content">
        <div className="dashboard-hero" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h1 className="dashboard-hero__title">Question Bank</h1>
            <p className="dashboard-hero__subtitle text-secondary">
              Author, organize, and archive multiple-choice questions for examination snapshots.
            </p>
          </div>
          <button
            type="button"
            className="btn btn--primary"
            onClick={openCreateModal}
          >
            <Plus className="btn__icon" aria-hidden="true" /> New Question
          </button>
        </div>

        {/* Filter Toolbar */}
        <div className="filter-bar" style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem', alignItems: 'center' }}>
          <div style={{ position: 'relative', flex: '1', minWidth: '15rem' }}>
            <Search size={16} className="text-muted" style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)' }} aria-hidden="true" />
            <input
              type="text"
              placeholder="Search prompts…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="form-input"
              style={{ paddingLeft: '2.25rem' }}
            />
          </div>

          <div style={{ minWidth: '12rem' }}>
            <select
              value={selectedTopicId}
              onChange={(e) => setSelectedTopicId(e.target.value)}
              className="form-input"
              aria-label="Filter by Topic"
            >
              <option value="">All Topics</option>
              {topics.map((t) => (
                <option key={t.id} value={t.id}>
                  [{t.code}] {t.name}
                </option>
              ))}
            </select>
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.875rem', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(e) => setIncludeArchived(e.target.checked)}
            />
            <span className="text-secondary">Include Archived</span>
          </label>
        </div>

        {error && (
          <div className="inline-error" style={{ marginBottom: '1.5rem' }} role="alert">
            <AlertCircle className="inline-error__icon" aria-hidden="true" />
            <div style={{ flex: 1 }}>
              <p style={{ margin: '0 0 0.5rem 0' }}>{error}</p>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={loadQuestions}
              >
                <RotateCcw className="btn__icon" aria-hidden="true" /> Retry
              </button>
            </div>
          </div>
        )}

        {isLoading ? (
          <div style={{ textAlign: 'center', padding: '4rem 1rem' }} aria-busy="true">
            <LoadingSpinner label="Loading questions…" size="lg" />
            <p className="text-secondary" style={{ marginTop: '1rem' }}>
              Fetching question bank…
            </p>
          </div>
        ) : questions.length === 0 ? (
          <div className="exam-card exam-card--empty">
            <Filter className="exam-card__empty-icon" aria-hidden="true" />
            <h2 className="exam-card__empty-title">No questions found</h2>
            <p className="text-secondary">
              No questions matched the current filter or search criteria.
            </p>
            <button
              type="button"
              className="btn btn--primary"
              style={{ marginTop: '1rem' }}
              onClick={openCreateModal}
            >
              <Plus className="btn__icon" aria-hidden="true" /> Create First Question
            </button>
          </div>
        ) : (
          <div className="question-bank-list" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {questions.map((q) => {
              const isArchived = Boolean(q.archived_at);
              const isOwner = user?.id === q.author_id;

              return (
                <article
                  key={q.id}
                  className="exam-card"
                  style={{ opacity: isArchived ? 0.75 : 1 }}
                >
                  <div className="exam-card__header">
                    <div className="exam-card__title-row">
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                        {q.topic ? (
                          <span className="exam-badge" style={{ fontSize: '0.75rem' }}>
                            {q.topic.code} — {q.topic.name}
                          </span>
                        ) : (
                          <span className="exam-badge" style={{ fontSize: '0.75rem' }}>
                            Unassigned
                          </span>
                        )}
                        {isArchived && (
                          <span className="exam-badge" style={{ background: 'rgba(248, 113, 113, 0.15)', color: 'var(--color-error)' }}>
                            Archived
                          </span>
                        )}
                      </div>

                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        {!isArchived && isOwner && (
                          <>
                            <button
                              type="button"
                              className="btn btn--ghost btn--sm"
                              onClick={() => openEditModal(q)}
                              title="Edit question"
                            >
                              <Edit2 size={14} className="btn__icon" aria-hidden="true" /> Edit
                            </button>
                            <button
                              type="button"
                              className="btn btn--ghost btn--sm"
                              onClick={() => {
                                setArchivingQuestion(q);
                                setArchiveError(null);
                              }}
                              title="Archive question"
                            >
                              <Archive size={14} className="btn__icon" aria-hidden="true" /> Archive
                            </button>
                          </>
                        )}
                      </div>
                    </div>

                    <p style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--color-text)', margin: '0.5rem 0' }}>
                      {q.prompt}
                    </p>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(18rem, 1fr))', gap: '0.5rem', marginTop: '0.5rem' }}>
                    {q.options.map((opt) => (
                      <div
                        key={opt.id}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.5rem',
                          padding: '0.4rem 0.6rem',
                          background: opt.is_correct ? 'rgba(52, 211, 153, 0.1)' : 'var(--color-surface-2)',
                          border: `1px solid ${opt.is_correct ? 'rgba(52, 211, 153, 0.3)' : 'var(--color-border-subtle)'}`,
                          borderRadius: 'var(--radius-md)',
                          fontSize: '0.875rem',
                        }}
                      >
                        {opt.is_correct ? (
                          <CheckCircle2 size={15} className="text-success" aria-hidden="true" />
                        ) : (
                          <span style={{ width: '15px', height: '15px', borderRadius: '50%', border: '1px solid var(--color-border)', display: 'inline-block' }} />
                        )}
                        <span style={{ flex: 1, color: opt.is_correct ? 'var(--color-success)' : 'var(--color-text)' }}>
                          {opt.option_text}
                        </span>
                      </div>
                    ))}
                  </div>

                  <div style={{ marginTop: '0.75rem', fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                    Created: {new Date(q.created_at).toLocaleDateString()} {isArchived && `· Archived: ${new Date(q.archived_at!).toLocaleDateString()}`}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </main>

      {/* Editor Modal */}
      {isEditorOpen && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="editor-title">
          <div className="modal-content" style={{ maxWidth: '40rem' }}>
            <div className="modal-header">
              <h2 id="editor-title" className="modal-title">
                {editingQuestion ? 'Edit Question' : 'Create New Question'}
              </h2>
              <button
                type="button"
                className="btn-icon"
                onClick={() => { setIsEditorOpen(false); clearSuggestion(); }}
                disabled={isSaving}
                aria-label="Close"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            <form onSubmit={handleSaveQuestion}>
              <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {editorError && (
                  <div className="inline-error" role="alert">
                    <AlertCircle className="inline-error__icon" aria-hidden="true" />
                    <span>{editorError}</span>
                  </div>
                )}

                <div className="form-field">
                  <label htmlFor="q-prompt" className="form-label">
                    Question Prompt <span className="text-error">*</span>
                  </label>
                  <textarea
                    id="q-prompt"
                    value={promptInput}
                    onChange={(e) => handlePromptChange(e.target.value)}
                    className="form-input"
                    rows={3}
                    placeholder="Enter question prompt..."
                    required
                  />
                </div>

                <div className="form-field">
                  <label htmlFor="q-topic" className="form-label">
                    Taxonomy Topic (Optional)
                  </label>
                  <select
                    id="q-topic"
                    value={topicInput}
                    onChange={(e) => {
                      setTopicInput(e.target.value);
                      if (suggestionResult || suggestionUnavailableReason || suggestionError) {
                        clearSuggestion();
                      }
                    }}
                    className="form-input"
                  >
                    <option value="">No Topic Assigned</option>
                    {topics.map((t) => (
                      <option key={t.id} value={t.id}>
                        [{t.code}] {t.name}
                      </option>
                    ))}
                  </select>

                  {/* ML Suggest Topic action (M4-ML-UI-1) */}
                  <div style={{ marginTop: '0.5rem' }}>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      onClick={handleSuggestTopic}
                      disabled={isSuggesting || isSaving || !promptInput.trim()}
                      aria-busy={isSuggesting}
                      aria-label="Request an automatic topic suggestion from the ML classifier"
                      id="suggest-topic-btn"
                    >
                      {isSuggesting
                        ? <><LoadingSpinner size="sm" />&nbsp;Suggesting…</>
                        : <><Sparkles size={14} className="btn__icon" aria-hidden="true" />Suggest Topic</>}
                    </button>
                  </div>

                  {/* Suggestion result panel */}
                  {(suggestionResult || suggestionUnavailableReason || suggestionError) && (
                    <div
                      role="status"
                      aria-live="polite"
                      aria-atomic="true"
                      style={{
                        marginTop: '0.625rem',
                        padding: '0.75rem',
                        borderRadius: 'var(--radius-md)',
                        border: suggestionResult
                          ? '1px solid rgba(139, 92, 246, 0.35)'
                          : suggestionError
                          ? '1px solid rgba(248, 113, 113, 0.35)'
                          : '1px solid var(--color-border-subtle)',
                        background: suggestionResult
                          ? 'rgba(139, 92, 246, 0.08)'
                          : suggestionError
                          ? 'rgba(248, 113, 113, 0.08)'
                          : 'var(--color-surface-2)',
                        fontSize: '0.875rem',
                      }}
                    >
                      {/* High-confidence suggestion available */}
                      {suggestionResult && (
                        <>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.5rem' }}>
                            <Sparkles size={13} style={{ color: 'var(--color-accent)' }} aria-hidden="true" />
                            <span style={{ fontWeight: 600, color: 'var(--color-accent)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.03em' }}>
                              Automatic Topic Suggestion
                            </span>
                          </div>
                          <div style={{ marginBottom: '0.5rem' }}>
                            <span style={{ fontWeight: 600, color: 'var(--color-text)' }}>
                              {suggestionResult.topic_name}
                            </span>
                            <span style={{ color: 'var(--color-text-muted)', marginLeft: '0.4rem' }}>
                              [{suggestionResult.topic_code}]
                            </span>
                          </div>
                          <div style={{ color: 'var(--color-text-muted)', marginBottom: '0.625rem', fontSize: '0.8rem' }}>
                            Confidence: {Math.round(suggestionResult.confidence * 100)}%
                            {' '}(threshold: {Math.round(suggestionResult.threshold * 100)}%)
                          </div>
                          <div style={{ display: 'flex', gap: '0.5rem' }}>
                            <button
                              type="button"
                              className="btn btn--primary btn--sm"
                              onClick={handleUseSuggestion}
                              id="use-suggestion-btn"
                            >
                              Use Suggestion
                            </button>
                            <button
                              type="button"
                              className="btn btn--ghost btn--sm"
                              onClick={clearSuggestion}
                              id="dismiss-suggestion-btn"
                            >
                              Dismiss
                            </button>
                          </div>
                        </>
                      )}

                      {/* No suggestion available */}
                      {suggestionUnavailableReason && !suggestionResult && (
                        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.5rem' }}>
                          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem' }}>
                            <Sparkles size={13} style={{ color: 'var(--color-text-muted)', marginTop: '0.1rem', flexShrink: 0 }} aria-hidden="true" />
                            <span style={{ color: 'var(--color-text-muted)' }}>
                              {suggestionUnavailableReason === 'LOW_CONFIDENCE'
                                ? 'No confident topic suggestion — the classifier could not determine a topic with sufficient certainty. Please select a topic manually.'
                                : suggestionUnavailableReason === 'MODEL_NOT_FOUND' || suggestionUnavailableReason === 'MODEL_LOAD_FAILED'
                                ? 'The ML topic classifier is not currently available. Please select a topic manually.'
                                : 'Topic suggestion unavailable. Please select a topic manually.'}
                            </span>
                          </div>
                          <button
                            type="button"
                            className="btn-icon"
                            onClick={clearSuggestion}
                            aria-label="Dismiss message"
                            title="Dismiss"
                            style={{ padding: '2px', color: 'var(--color-text-muted)', flexShrink: 0 }}
                          >
                            <X size={14} aria-hidden="true" />
                          </button>
                        </div>
                      )}

                      {/* Network or API error — separate from form validation */}
                      {suggestionError && !suggestionResult && (
                        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.5rem' }}>
                          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem' }}>
                            <AlertCircle size={13} style={{ color: 'var(--color-error)', marginTop: '0.1rem', flexShrink: 0 }} aria-hidden="true" />
                            <span style={{ color: 'var(--color-error)' }}>
                              {suggestionError}
                            </span>
                          </div>
                          <button
                            type="button"
                            className="btn-icon"
                            onClick={clearSuggestion}
                            aria-label="Dismiss error"
                            title="Dismiss"
                            style={{ padding: '2px', color: 'var(--color-error)', flexShrink: 0 }}
                          >
                            <X size={14} aria-hidden="true" />
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <label className="form-label" style={{ margin: 0 }}>
                      Answer Options (2 to 6, select 1 correct) <span className="text-error">*</span>
                    </label>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      onClick={handleAddOption}
                      disabled={optionsDraft.length >= 6 || isSaving}
                    >
                      <Plus size={14} className="btn__icon" aria-hidden="true" /> Add Option
                    </button>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {optionsDraft.map((opt, idx) => (
                      <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <input
                          type="radio"
                          name="correctOptionGroup"
                          id={`correct-opt-${idx}`}
                          checked={opt.is_correct}
                          onChange={() => handleSetCorrect(idx)}
                          aria-label={`Mark option ${idx + 1} as correct`}
                          style={{ cursor: 'pointer' }}
                        />
                        <input
                          type="text"
                          value={opt.text}
                          onChange={(e) => handleOptionTextChange(idx, e.target.value)}
                          placeholder={`Option ${idx + 1}`}
                          className="form-input"
                          style={{ flex: 1 }}
                          required
                        />
                        <button
                          type="button"
                          className="btn-icon"
                          onClick={() => handleRemoveOption(idx)}
                          disabled={optionsDraft.length <= 2 || isSaving}
                          title="Remove option"
                          aria-label={`Remove option ${idx + 1}`}
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => { setIsEditorOpen(false); clearSuggestion(); }}
                  disabled={isSaving}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn--primary"
                  disabled={isSaving}
                  aria-busy={isSaving}
                >
                  {isSaving ? <LoadingSpinner size="sm" /> : editingQuestion ? 'Save Changes' : 'Create Question'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Archive Modal */}
      {archivingQuestion && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="archive-title">
          <div className="modal-content" style={{ maxWidth: '30rem' }}>
            <div className="modal-header">
              <h2 id="archive-title" className="modal-title">
                Archive Question?
              </h2>
              <button
                type="button"
                className="btn-icon"
                onClick={() => setArchivingQuestion(null)}
                disabled={isArchiving}
                aria-label="Close"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            <div className="modal-body">
              <p className="text-secondary" style={{ marginBottom: '1rem' }}>
                Archiving this question will hide it from future exam draft authoring. Existing published examination snapshots that already include this question will remain completely unaffected.
              </p>

              <div style={{ padding: '0.75rem', background: 'var(--color-surface-2)', borderRadius: 'var(--radius-md)', fontSize: '0.875rem' }}>
                &ldquo;{archivingQuestion.prompt}&rdquo;
              </div>

              {archiveError && (
                <div className="inline-error" style={{ marginTop: '1rem' }} role="alert">
                  <AlertCircle className="inline-error__icon" aria-hidden="true" />
                  <span>{archiveError}</span>
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setArchivingQuestion(null)}
                disabled={isArchiving}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn--primary"
                onClick={handleConfirmArchive}
                disabled={isArchiving}
                aria-busy={isArchiving}
              >
                {isArchiving ? <LoadingSpinner size="sm" /> : 'Confirm Archive'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
