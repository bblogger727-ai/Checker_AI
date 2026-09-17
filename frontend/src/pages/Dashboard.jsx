import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../App';
import {
    getExams, createExam, deleteExam,
    getPaperCatalog, getPipelineJobs,
    runOldPipeline, runNewPipeline, runFeedbackPipeline, precheckAnswerSheet,
    getPipelineStatus, downloadPipelineResult, pipelineAction,
    recheckPipeline,
    getStats, resetStats,
    removeFromQueue, pauseQueue, resumeQueue,
} from '../services/api';
import './Dashboard.css';

/* ── Tiny helpers ─────────────────────────────────────────────────────────── */

function saveBlob(blob, filename) {
    const url = window.URL.createObjectURL(blob);
    const a   = document.createElement('a');
    a.href     = url;
    a.download = filename;
    a.click();
    window.URL.revokeObjectURL(url);
}

const STAGE_LABELS = {
    started:         'Starting pipeline…',
    stage_1:         'Stage 1 — Extracting question schema',
    stage_1_2:       'Stage 1+2 — Building schema from paper JSON',
    stage_2:         'Stage 2 — Extracting model answers',
    stage_3:         'Stage 3 — Running OCR on student answer sheet',
    stage_4:         'Stage 4 — Aligning answers',
    stage_5:         'Stage 5 — Grading with Claude',
    stage_6:         'Stage 6 — Generating PDF report',
    stage_7:         'Stage 7 — Annotating checked copy',
    recheck:         'Re-generating checked copy (Stage 7)…',
    recheck_failed:  'Checked copy generation failed',
    completed:       'Complete!',
    failed:          'Failed',
};

const STAGE_IDX = ['started','stage_1','stage_1_2','stage_2','stage_3','stage_4','stage_5','stage_6','stage_7','completed'];

/* ── Progress bar component ───────────────────────────────────────────────── */

function ProgressBar({ stage }) {
    const idx     = STAGE_IDX.indexOf(stage);
    const total   = STAGE_IDX.length - 1;
    const pct     = stage === 'completed' ? 100 : Math.round(((idx < 0 ? 0 : idx) / total) * 100);
    return (
        <div className="progress-track">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
            <span className="progress-pct">{pct}%</span>
        </div>
    );
}

/* ── File drop zone ───────────────────────────────────────────────────────── */

function DropZone({ label, id, accept = '.pdf', file, onChange }) {
    const inputRef = useRef();
    const [drag, setDrag] = useState(false);

    const onDrop = useCallback((e) => {
        e.preventDefault();
        setDrag(false);
        const f = e.dataTransfer?.files?.[0];
        if (f) onChange(f);
    }, [onChange]);

    return (
        <div
            id={id}
            className={`drop-zone ${drag ? 'drag-over' : ''} ${file ? 'has-file' : ''}`}
            onClick={() => inputRef.current.click()}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
        >
            <input
                ref={inputRef}
                type="file"
                accept={accept}
                style={{ display: 'none' }}
                onChange={(e) => onChange(e.target.files[0])}
            />
            <div className="drop-icon">{file ? '✅' : '📄'}</div>
            <div className="drop-label">{label}</div>
            <div className="drop-hint">
                {file ? file.name : 'Click or drag & drop PDF'}
            </div>
        </div>
    );
}

/* ── Result card shown after pipeline completes ───────────────────────────── */

function ResultCard({ status, taskId, studentName, onReset, navigate }) {
    const [downloading, setDownloading] = useState('');
    const meta = status || {};

    const download = async (fileType) => {
        setDownloading(fileType);
        try {
            const blob = await downloadPipelineResult(taskId, fileType);
            const name = fileType === 'checked_copy'
                ? `${studentName}_checked_copy.pdf`
                : fileType === 'student_report'
                ? `${studentName}_report.txt`
                : `${studentName}_grading_report.pdf`;
            saveBlob(blob, name);
        } catch (err) {
            alert('Download failed: ' + (err.response?.data?.detail || err.message));
        } finally {
            setDownloading('');
        }
    };

    return (
        <div className="result-card">
            <div className="result-icon">🎉</div>
            <h3 className="result-title">Grading Complete!</h3>
            {meta.total_marks_obtained != null && (
                <div className="result-score">
                    <span className="score-big">{meta.total_marks_obtained}</span>
                    <span className="score-sep">/</span>
                    <span className="score-total">{meta.total_marks_possible}</span>
                    <span className="score-grade grade-pill">{meta.grade}</span>
                </div>
            )}
            {meta.percentage != null && (
                <div className="result-pct">{+Number(meta.percentage).toFixed(2)}%</div>
            )}
            {meta.scoring_rule && (
                <p className="result-rule">{meta.scoring_rule}</p>
            )}
            <div className="result-actions">
                <button
                    id="dl-checked-copy-btn"
                    className="dl-btn primary-dl"
                    onClick={() => download('checked_copy')}
                    disabled={!meta.checked_copy_ready || downloading === 'checked_copy'}
                >
                    {downloading === 'checked_copy' ? '⏳ Preparing…' : '⬇ Download Checked Copy'}
                </button>
                <button
                    id="dl-report-btn"
                    className="dl-btn secondary-dl"
                    onClick={() => download('grading_report')}
                    disabled={!meta.grading_report_ready || downloading === 'grading_report'}
                >
                    {downloading === 'grading_report' ? '⏳ Preparing…' : '📊 Download Grading Report'}
                </button>
                <button
                    id="dl-student-report-btn"
                    className="dl-btn secondary-dl"
                    style={{ backgroundColor: '#2b2d31', borderColor: '#4a4d55' }}
                    onClick={() => download('student_report')}
                    disabled={!meta.student_report_txt || downloading === 'student_report'}
                >
                    {downloading === 'student_report' ? '⏳ Preparing…' : '📄 View Student Report'}
                </button>
                <button
                    id="edit-checked-copy-btn"
                    className="dl-btn secondary-dl"
                    style={{ backgroundColor: '#2b2d31', borderColor: '#4a4d55' }}
                    onClick={() => navigate(`/checked-paper/${taskId}/edit`)}
                    disabled={!meta.checked_copy_ready}
                >
                    ✏️ Edit Checked Paper
                </button>
            </div>
            <button id="check-another-btn" className="reset-btn" onClick={onReset}>
                ← Check Another Paper
            </button>
        </div>
    );
}

/* ══════════════════════════════════════════════════════════════════════════ */

/* ── Toast notification ───────────────────────────────────────────────────── */
function Toast({ message, onDone }) {
    useEffect(() => {
        const t = setTimeout(onDone, 3200);
        return () => clearTimeout(t);
    }, [onDone]);
    return (
        <div style={{
            position: 'fixed', bottom: '32px', left: '50%', transform: 'translateX(-50%)',
            background: '#23a559', color: '#fff', padding: '14px 28px',
            borderRadius: '10px', fontWeight: '600', fontSize: '1rem',
            boxShadow: '0 4px 24px rgba(0,0,0,0.35)', zIndex: 9999,
            animation: 'slideUp .25s ease',
        }}>
            {message}
        </div>
    );
}

/* ── Lifetime Stats badge (top-right, no reset) ───────────────────────────── */
function LifetimeStats({ profile }) {
    const [lifetime, setLifetime] = useState({ total: 0, full: 0, portionwise: 0 });

    const fetchLifetime = useCallback(async () => {
        try {
            const data = await getStats();
            const lt = data?.["__lifetime__"]?.[profile];
            if (lt) setLifetime(lt);
        } catch (e) { /* silent */ }
    }, [profile]);

    useEffect(() => {
        fetchLifetime();
        const iv = setInterval(fetchLifetime, 8000);
        return () => clearInterval(iv);
    }, [fetchLifetime]);

    return (
        <div style={{
            display: 'flex', alignItems: 'center', gap: '10px',
            background: 'linear-gradient(135deg, #2c2f33 0%, #23272a 100%)',
            border: '1px solid #5865f2', borderRadius: '8px',
            padding: '8px 14px', fontSize: '13px', color: '#b5bac1',
        }}>
            <span style={{ fontSize: '18px' }}>🏆</span>
            <div>
                <div style={{ color: '#fff', fontWeight: 700, fontSize: '14px' }}>
                    {lifetime.total} Total Lifetime
                </div>
                <div style={{ fontSize: '11px', color: '#72767d' }}>
                    {lifetime.full} Mock &nbsp;·&nbsp; {lifetime.portionwise} Portionwise
                </div>
            </div>
        </div>
    );
}

function ProfileStats({ profile }) {
    const [stats, setStats] = useState({ total: 0, full: 0, portionwise: 0 });

    const fetchStats = useCallback(async () => {
        try {
            const data = await getStats();
            if (data[profile]) {
                setStats(data[profile]);
            } else {
                setStats({ total: 0, full: 0, portionwise: 0 });
            }
        } catch (e) {
            console.error("Failed to fetch stats", e);
        }
    }, [profile]);

    useEffect(() => {
        fetchStats();
        // Set up a polling interval to update stats
        const interval = setInterval(fetchStats, 5000);
        return () => clearInterval(interval);
    }, [fetchStats]);

    const handleReset = async () => {
        try {
            const res = await resetStats(profile);
            if (res.stats) setStats(res.stats);
        } catch (e) {
            console.error("Failed to reset stats", e);
        }
    };

    return (
        <div style={{ backgroundColor: '#1e1f22', padding: '10px 15px', borderRadius: '6px', marginBottom: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
                <div style={{ fontSize: '14px', color: '#b5bac1' }}>
                    <strong style={{ color: '#fff' }}>{profile} Usage:</strong>&nbsp;
                    <span style={{ marginRight: '15px' }}>{stats.total} Total checked</span>
                    <span style={{ marginRight: '15px', color: '#5865f2' }}>{stats.full} Mock (Full)</span>
                    <span style={{ color: '#23a559' }}>{stats.portionwise} Portionwise</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <LifetimeStats profile={profile} />
                    <button type="button" className="reset-btn" onClick={handleReset} style={{ margin: 0, padding: '4px 10px', fontSize: '12px' }}>
                        Reset Count
                    </button>
                </div>
            </div>
        </div>
    );
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* OLD PAPERS TAB                                                             */
/* ══════════════════════════════════════════════════════════════════════════ */

function OldPapersTab() {
    const [form, setForm]                   = useState({ studentName: '', qpPdf: null, saPdf: null, asPdf: null, profile: 'Profile 1' });
    const [submitting, setSubmitting]       = useState(false);
    const [toast, setToast]                 = useState(null);
    const [errorMsg, setErrorMsg]           = useState(null);
    const [horizontalWarn, setHorizontalWarn] = useState(false);  // pre-check warning state
    const pendingSubmitRef = useRef(null);                        // stores the form data while user decides

    const _doQueue = async (formData) => {
        setSubmitting(true);
        setHorizontalWarn(false);
        try {
            await runOldPipeline(formData.studentName, formData.qpPdf, formData.saPdf, formData.asPdf, formData.profile);
            const name = formData.studentName.trim() || 'Paper';
            setToast(`✅ ${name} has been queued for checking!`);
            setForm(prev => ({ studentName: '', qpPdf: null, saPdf: null, asPdf: null, profile: prev.profile }));
            pendingSubmitRef.current = null;
        } catch (err) {
            setErrorMsg(err.response?.data?.detail || err.message);
        } finally {
            setSubmitting(false);
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setErrorMsg(null);
        setHorizontalWarn(false);
        const { qpPdf, saPdf, asPdf } = form;
        if (!qpPdf || !saPdf || !asPdf) {
            setErrorMsg('Please provide all three PDFs (Question, Solution, Student).');
            return;
        }
        // Pre-check for horizontal pages before queuing
        setSubmitting(true);
        try {
            const { has_horizontal } = await precheckAnswerSheet(asPdf);
            if (has_horizontal) {
                pendingSubmitRef.current = { ...form };
                setHorizontalWarn(true);
                setSubmitting(false);
                return;
            }
        } catch (_) {
            // If pre-check fails, proceed normally (don't block)
        }
        setSubmitting(false);
        await _doQueue(form);
    };

    return (
        <form className="pipeline-form" onSubmit={handleSubmit}>
            {toast && <Toast message={toast} onDone={() => setToast(null)} />}

            {/* Horizontal pages warning — shown BEFORE queuing */}
            {horizontalWarn && (
                <div style={{
                    background: '#2d2213', border: '1.5px solid #f0a500', borderRadius: '10px',
                    padding: '14px 18px', marginBottom: '16px', color: '#f0c040',
                }}>
                    <strong>⚠️ Horizontal / Rotated Pages Detected</strong>
                    <p style={{ margin: '6px 0 12px', fontSize: '13px', color: '#c8a84b' }}>
                        This answer sheet contains landscape-oriented or rotated pages.
                        OCR and annotation accuracy may be reduced. Do you still want to continue?
                    </p>
                    <div style={{ display: 'flex', gap: '10px' }}>
                        <button type="button" className="submit-btn"
                            onClick={() => _doQueue(pendingSubmitRef.current)}
                            disabled={submitting}
                        >
                            {submitting ? '⏳ Queuing…' : '✅ Continue Anyway'}
                        </button>
                        <button type="button" className="cancel-btn"
                            onClick={() => { setHorizontalWarn(false); pendingSubmitRef.current = null; }}
                            disabled={submitting}
                        >
                            ✕ Cancel
                        </button>
                    </div>
                </div>
            )}

            <p className="pipeline-desc">
                Provide all three documents. Claude AI will extract the schema from the question
                paper, model answers from the solution, OCR the student sheet, align answers,
                grade, and produce an annotated checked copy.
            </p>

            <div className="form-field">
                <label className="field-lbl" htmlFor="old-profile">Profile API Key</label>
                <select
                    id="old-profile"
                    className="text-input"
                    value={form.profile}
                    onChange={(e) => setForm({ ...form, profile: e.target.value })}
                    disabled={submitting}
                >
                    <option value="Profile 1">Profile 1 (Default)</option>
                    <option value="Profile 2">Profile 2</option>
                </select>
                <div style={{ marginTop: '10px' }}>
                    <ProfileStats profile={form.profile} />
                </div>
            </div>

            <div className="form-field">
                <label className="field-lbl" htmlFor="old-student-name">Student Name (Optional)</label>
                <input
                    id="old-student-name"
                    className="text-input"
                    type="text"
                    placeholder="e.g. Rahul Sharma"
                    value={form.studentName}
                    onChange={(e) => setForm({ ...form, studentName: e.target.value })}
                    disabled={submitting}
                />
            </div>

            <div className="drop-grid three-col">
                <DropZone
                    id="dz-qp"
                    label="Question Paper"
                    file={form.qpPdf}
                    onChange={(f) => setForm({ ...form, qpPdf: f })}
                />
                <DropZone
                    id="dz-sa"
                    label="Solution / Model Answers"
                    file={form.saPdf}
                    onChange={(f) => setForm({ ...form, saPdf: f })}
                />
                <DropZone
                    id="dz-as-old"
                    label="Student Answer Sheet"
                    file={form.asPdf}
                    onChange={(f) => setForm({ ...form, asPdf: f })}
                />
            </div>

            {errorMsg && (
                <div className="pipeline-error">
                    <span>⚠️ {errorMsg}</span>
                    <div className="pipeline-error-actions">
                        <button type="button" className="reset-btn" onClick={() => setErrorMsg(null)}>Dismiss</button>
                    </div>
                </div>
            )}

            <button id="old-run-btn" type="submit" className="run-btn" disabled={submitting}>
                {submitting ? '⏳ Queuing…' : '🚀 Queue for Checking'}
            </button>

            <p style={{ textAlign: 'center', color: '#72767d', fontSize: '13px', marginTop: '8px' }}>
                💡 Progress is tracked in the <strong>Checked Papers</strong> tab
            </p>
        </form>
    );
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* NEW PAPERS TAB                                                             */
/* ══════════════════════════════════════════════════════════════════════════ */

function NewPapersTab() {
    const [catalog, setCatalog]   = useState(null);
    const [catalogError, setCatalogError] = useState(false);
    const [sel,     setSel]       = useState({ exam: '', subject: '', type: '', paper: '' });
    const [form,    setForm]      = useState({ studentName: '', asPdf: null, profile: 'Profile 1' });
    const [submitting, setSubmitting] = useState(false);
    const [toast, setToast]       = useState(null);
    const [errorMsg, setErrorMsg] = useState(null);

    const loadCatalog = useCallback(() => {
        setCatalogError(false);
        getPaperCatalog()
            .then(setCatalog)
            .catch((err) => {
                console.error('Catalog fetch error:', err);
                setCatalogError(true);
            });
    }, []);

    useEffect(() => { loadCatalog(); }, [loadCatalog]);

    const exams    = catalog ? Object.keys(catalog).sort() : [];
    const subjects = sel.exam && catalog?.[sel.exam] ? Object.keys(catalog[sel.exam]).sort() : [];
    const types    = sel.subject && catalog?.[sel.exam]?.[sel.subject]
        ? Object.entries(catalog[sel.exam][sel.subject])
              .filter(([, arr]) => arr.length > 0)
              .map(([t]) => t)
        : [];
    const papers   = (sel.type && catalog?.[sel.exam]?.[sel.subject]?.[sel.type]) || [];
    const selectedPaperPath = papers.find(p => p.filename === sel.paper)?.path || '';

    const [horizontalWarn, setHorizontalWarn] = useState(false);
    const pendingSubmitRef = useRef(null);

    const _doQueue = async (formData, paperPath, paperLabel) => {
        setSubmitting(true);
        setHorizontalWarn(false);
        try {
            await runNewPipeline(formData.studentName, paperPath, formData.asPdf, formData.profile);
            const name = formData.studentName.trim() || 'Paper';
            setToast(`✅ ${name} — ${paperLabel} queued for checking!`);
            setForm(prev => ({ studentName: '', asPdf: null, profile: prev.profile }));
            setSel({ exam: '', subject: '', type: '', paper: '' });
            pendingSubmitRef.current = null;
        } catch (err) {
            setErrorMsg(err.response?.data?.detail || err.message);
        } finally {
            setSubmitting(false);
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setErrorMsg(null);
        setHorizontalWarn(false);
        if (!selectedPaperPath || !form.asPdf) {
            setErrorMsg('Please select a paper and provide the student answer sheet.');
            return;
        }
        const paperLabel = papers.find(p => p.filename === sel.paper)?.label || '';
        // Pre-check for horizontal pages before queuing
        setSubmitting(true);
        try {
            const { has_horizontal } = await precheckAnswerSheet(form.asPdf);
            if (has_horizontal) {
                pendingSubmitRef.current = { form: { ...form }, paperPath: selectedPaperPath, paperLabel };
                setHorizontalWarn(true);
                setSubmitting(false);
                return;
            }
        } catch (_) {
            // If pre-check fails, proceed normally
        }
        setSubmitting(false);
        await _doQueue(form, selectedPaperPath, paperLabel);
    };

    return (
        <form className="pipeline-form" onSubmit={handleSubmit}>
            {toast && <Toast message={toast} onDone={() => setToast(null)} />}

            {/* Horizontal pages warning — shown BEFORE queuing */}
            {horizontalWarn && (
                <div style={{
                    background: '#2d2213', border: '1.5px solid #f0a500', borderRadius: '10px',
                    padding: '14px 18px', marginBottom: '16px', color: '#f0c040',
                }}>
                    <strong>⚠️ Horizontal / Rotated Pages Detected</strong>
                    <p style={{ margin: '6px 0 12px', fontSize: '13px', color: '#c8a84b' }}>
                        This answer sheet contains landscape-oriented or rotated pages.
                        OCR and annotation accuracy may be reduced. Do you still want to continue?
                    </p>
                    <div style={{ display: 'flex', gap: '10px' }}>
                        <button type="button" className="submit-btn"
                            onClick={() => { const p = pendingSubmitRef.current; _doQueue(p.form, p.paperPath, p.paperLabel); }}
                            disabled={submitting}
                        >
                            {submitting ? '⏳ Queuing…' : '✅ Continue Anyway'}
                        </button>
                        <button type="button" className="cancel-btn"
                            onClick={() => { setHorizontalWarn(false); pendingSubmitRef.current = null; }}
                            disabled={submitting}
                        >
                            ✕ Cancel
                        </button>
                    </div>
                </div>
            )}

            <p className="pipeline-desc">
                Select a pre-built paper from our library, upload the student answer sheet,
                and the FT pipeline will handle OCR, sub-part alignment, grading, and
                the annotated checked copy automatically.
            </p>

            <div className="form-field">
                <label className="field-lbl" htmlFor="new-profile">Profile API Key</label>
                <select
                    id="new-profile"
                    className="text-input"
                    value={form.profile}
                    onChange={(e) => setForm({ ...form, profile: e.target.value })}
                    disabled={submitting}
                >
                    <option value="Profile 1">Profile 1 (Default)</option>
                    <option value="Profile 2">Profile 2</option>
                </select>
                <div style={{ marginTop: '10px' }}>
                    <ProfileStats profile={form.profile} />
                </div>
            </div>

            <div className="form-field">
                <label className="field-lbl" htmlFor="new-student-name">Student Name (Optional)</label>
                <input
                    id="new-student-name"
                    className="text-input"
                    type="text"
                    placeholder="e.g. Priya Mehta"
                    value={form.studentName}
                    onChange={(e) => setForm({ ...form, studentName: e.target.value })}
                    disabled={submitting}
                />
            </div>

            {catalogError && (
                <div className="pipeline-error" style={{ marginBottom: '15px' }}>
                    ⚠️ Failed to load paper catalog.
                    <button type="button" className="reset-btn" style={{ marginLeft: '15px' }} onClick={loadCatalog}>
                        Retry Loading
                    </button>
                </div>
            )}

            {/* Cascading dropdowns */}
            <div className="cascade-grid">
                <div className="form-field">
                    <label className="field-lbl" htmlFor="dd-exam">Exam Level *</label>
                    <select
                        id="dd-exam"
                        className="select-input"
                        value={sel.exam}
                        onChange={(e) => setSel({ exam: e.target.value, subject: '', type: '', paper: '' })}
                        disabled={submitting || !catalog}
                    >
                        <option value="">Select exam…</option>
                        {exams.map(ex => <option key={ex} value={ex}>{ex}</option>)}
                    </select>
                </div>

                <div className="form-field">
                    <label className="field-lbl" htmlFor="dd-subject">Subject *</label>
                    <select
                        id="dd-subject"
                        className="select-input"
                        value={sel.subject}
                        onChange={(e) => setSel({ ...sel, subject: e.target.value, type: '', paper: '' })}
                        disabled={submitting || !sel.exam}
                    >
                        <option value="">Select subject…</option>
                        {subjects.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
                    </select>
                </div>

                <div className="form-field">
                    <label className="field-lbl" htmlFor="dd-type">Test Type *</label>
                    <select
                        id="dd-type"
                        className="select-input"
                        value={sel.type}
                        onChange={(e) => setSel({ ...sel, type: e.target.value, paper: '' })}
                        disabled={submitting || !sel.subject}
                    >
                        <option value="">Select type…</option>
                        {types.map(t => <option key={t} value={t}>{t} Test</option>)}
                    </select>
                </div>

                <div className="form-field">
                    <label className="field-lbl" htmlFor="dd-paper">Paper *</label>
                    <select
                        id="dd-paper"
                        className="select-input"
                        value={sel.paper}
                        onChange={(e) => setSel({ ...sel, paper: e.target.value })}
                        disabled={submitting || !sel.type}
                    >
                        <option value="">Select paper…</option>
                        {papers.map(p => (
                            <option key={p.filename} value={p.filename}>{p.label}</option>
                        ))}
                    </select>
                </div>
            </div>

            {/* Selected paper pill */}
            {selectedPaperPath && (
                <div className="selected-paper-pill">
                    📋 {sel.exam} · {sel.subject.replace(/_/g, ' ')} · {papers.find(p => p.filename === sel.paper)?.label}
                </div>
            )}

            <div className="drop-grid one-col">
                <DropZone
                    id="dz-as-new"
                    label="Student Answer Sheet"
                    file={form.asPdf}
                    onChange={(f) => setForm({ ...form, asPdf: f })}
                />
            </div>

            {errorMsg && (
                <div className="pipeline-error">
                    <span>⚠️ {errorMsg}</span>
                    <div className="pipeline-error-actions">
                        <button type="button" className="reset-btn" onClick={() => setErrorMsg(null)}>Dismiss</button>
                    </div>
                </div>
            )}

            <button id="new-run-btn" type="submit" className="run-btn" disabled={!selectedPaperPath || submitting}>
                {submitting ? '⏳ Queuing…' : '🚀 Queue for Checking'}
            </button>

            <p style={{ textAlign: 'center', color: '#72767d', fontSize: '13px', marginTop: '8px' }}>
                💡 Progress is tracked in the <strong>Checked Papers</strong> tab
            </p>
        </form>
    );
}

/* ── Feedback Pipeline Tab ────────────────────────────────────────────────── */

function FeedbackTab() {
    const [studentName, setStudentName] = useState('');
    const [saPdf, setSaPdf] = useState(null);
    const [asPdf, setAsPdf] = useState(null);
    const [marks, setMarks] = useState([{ question: '', marks: '', totalMarks: '' }]);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [job, setJob] = useState(null); // { taskId, status, stage, ... }
    const [errorMsg, setErrorMsg] = useState('');
    const navigate = useNavigate();

    // Polling effect
    useEffect(() => {
        if (!job?.taskId || job.status === 'completed' || job.status === 'failed') return;
        const interval = setInterval(async () => {
            try {
                const res = await getPipelineStatus(job.taskId);
                setJob(prev => ({ ...prev, ...res }));
            } catch (err) {
                console.error("Polling error:", err);
            }
        }, 2000);
        return () => clearInterval(interval);
    }, [job?.taskId, job?.status]);

    const handleAddMark = () => {
        setMarks([...marks, { question: '', marks: '', totalMarks: '' }]);
    };

    const handleRemoveMark = (index) => {
        setMarks(marks.filter((_, i) => i !== index));
    };

    const handleMarkChange = (index, field, value) => {
        const newMarks = [...marks];
        newMarks[index][field] = value;
        setMarks(newMarks);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setErrorMsg('');
        
        // Validation
        if (!saPdf) return setErrorMsg('Solution PDF is required');
        if (!asPdf) return setErrorMsg('Student Answer Sheet is required');
        
        const validMarks = marks.filter(m => m.question.trim() && m.marks.trim());
        if (validMarks.length === 0) return setErrorMsg('Please enter at least one question mark');
        
        const marksObj = { marks: {} };
        validMarks.forEach(m => {
            const parsedScored = parseFloat(m.marks);
            if (m.totalMarks.trim()) {
                marksObj.marks[m.question.trim()] = { 
                    scored: parsedScored, 
                    allotted: parseFloat(m.totalMarks) 
                };
            } else {
                marksObj.marks[m.question.trim()] = parsedScored;
            }
        });

        try {
            setIsSubmitting(true);
            const res = await runFeedbackPipeline(studentName, saPdf, asPdf, JSON.stringify(marksObj));
            setJob({ taskId: res.task_id, status: 'started', stage: 'started' });
        } catch (err) {
            setErrorMsg(err.response?.data?.detail || err.message);
        } finally {
            setIsSubmitting(false);
        }
    };

    if (job) {
        return (
            <div className="tab-pane pipeline-pane">
                <h3>Feedback Pipeline Progress</h3>
                <ProgressBar stage={job.stage} />
                <ResultCard
                    status={job}
                    taskId={job.taskId}
                    studentName={job.student_name || studentName}
                    onReset={() => setJob(null)}
                    navigate={navigate}
                />
            </div>
        );
    }

    return (
        <div className="tab-pane pipeline-pane">
            <div className="pipeline-header">
                <h3>💬 Feedback Only Pipeline</h3>
                <p>Run specialized feedback generation based on manually input marks.</p>
            </div>
            
            <form className="pipeline-form" onSubmit={handleSubmit}>
                {errorMsg && <div className="error-banner">{errorMsg}</div>}
                
                <div className="form-group">
                    <label>Student Name (Optional)</label>
                    <input 
                        type="text" 
                        value={studentName} 
                        onChange={e => setStudentName(e.target.value)}
                        placeholder="e.g. John Doe"
                    />
                </div>

                <div className="dropzone-row">
                    <DropZone label="Solution PDF" id="sa-pdf" file={saPdf} onChange={setSaPdf} />
                    <DropZone label="Student Answer Sheet" id="as-pdf" file={asPdf} onChange={setAsPdf} />
                </div>

                <div className="marks-interface">
                    <h4>Student Marks</h4>
                    <p className="marks-desc">Enter the marks scored for each question attempted.</p>
                    
                    <div className="marks-list">
                        {marks.map((mark, index) => (
                            <div key={index} className="mark-row">
                                <input
                                    type="text"
                                    placeholder="Question (e.g. Q1A)"
                                    value={mark.question}
                                    onChange={(e) => handleMarkChange(index, 'question', e.target.value)}
                                    className="mark-input"
                                />
                                <input
                                    type="number"
                                    step="0.5"
                                    placeholder="Marks scored"
                                    value={mark.marks}
                                    onChange={(e) => handleMarkChange(index, 'marks', e.target.value)}
                                    className="mark-input"
                                />
                                <span className="mark-separator">/</span>
                                <input
                                    type="number"
                                    step="0.5"
                                    placeholder="Total (opt)"
                                    value={mark.totalMarks}
                                    onChange={(e) => handleMarkChange(index, 'totalMarks', e.target.value)}
                                    className="mark-input total-mark-input"
                                />
                                {marks.length > 1 && (
                                    <button 
                                        type="button" 
                                        className="btn-icon remove-btn"
                                        onClick={() => handleRemoveMark(index)}
                                    >✕</button>
                                )}
                            </div>
                        ))}
                    </div>
                    <button type="button" className="btn-outline add-mark-btn" onClick={handleAddMark}>
                        + Add Question
                    </button>
                </div>

                <button type="submit" className="btn-primary" disabled={isSubmitting}>
                    {isSubmitting ? 'Starting...' : 'Run Pipeline'}
                </button>
            </form>
        </div>
    );
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* EXAMS LIST TAB  (existing exam/student management)                         */
/* ══════════════════════════════════════════════════════════════════════════ */

function ExamsTab() {
    const navigate = useNavigate();
    const [exams,      setExams]      = useState([]);
    const [loading,    setLoading]    = useState(true);
    const [showCreate, setShowCreate] = useState(false);
    const [creating,   setCreating]   = useState(false);
    const [newExam,    setNewExam]    = useState({ name: '', subject: '', examDate: '', solutionPdf: null });

    useEffect(() => { loadExams(); }, []);

    const loadExams = async () => {
        try { setExams(await getExams()); }
        catch (err) { console.error(err); }
        finally { setLoading(false); }
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        if (!newExam.solutionPdf) { alert('Please select a solution PDF'); return; }
        setCreating(true);
        try {
            await createExam(newExam.name, newExam.subject, newExam.examDate, newExam.solutionPdf);
            setShowCreate(false);
            setNewExam({ name: '', subject: '', examDate: '', solutionPdf: null });
            loadExams();
        } catch (err) {
            alert('Failed: ' + (err.response?.data?.detail || err.message));
        } finally { setCreating(false); }
    };

    const handleDelete = async (id, e) => {
        e.stopPropagation();
        if (!confirm('Delete this exam?')) return;
        try { await deleteExam(id); loadExams(); }
        catch { alert('Failed to delete'); }
    };

    const statusClass = (s) => ({ ready: 'status-ready', processing: 'status-processing', pending: 'status-pending' }[s] || 'status-failed');

    return (
        <div className="exams-tab">
            <div className="tab-header-row">
                <h2 className="tab-section-title">Your Exams</h2>
                <button id="create-exam-btn" className="create-btn" onClick={() => setShowCreate(true)}>+ New Exam</button>
            </div>

            {loading ? (
                <div className="loading">Loading exams…</div>
            ) : exams.length === 0 ? (
                <div className="empty-state">
                    <div className="empty-icon">📋</div>
                    <h3>No exams yet</h3>
                    <p>Create your first exam to start evaluating student papers</p>
                    <button onClick={() => setShowCreate(true)} className="create-btn">Create Exam</button>
                </div>
            ) : (
                <div className="exams-grid">
                    {exams.map(exam => (
                        <div key={exam.id} className="exam-card" onClick={() => navigate(`/exam/${exam.id}`)}>
                            <div className="exam-header">
                                <h3>{exam.name}</h3>
                                <span className={`status-badge ${statusClass(exam.processing_status)}`}>{exam.processing_status}</span>
                            </div>
                            <div className="exam-details">
                                {exam.subject && <p className="subject">{exam.subject}</p>}
                                {exam.exam_date && <p className="date">{new Date(exam.exam_date).toLocaleDateString()}</p>}
                            </div>
                            <div className="exam-footer">
                                <span className="student-count">{exam.student_count} student{exam.student_count !== 1 ? 's' : ''}</span>
                                <button className="delete-btn" onClick={(e) => handleDelete(exam.id, e)}>🗑️</button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {showCreate && (
                <div className="modal-overlay" onClick={() => setShowCreate(false)}>
                    <div className="modal" onClick={(e) => e.stopPropagation()}>
                        <h2>Create New Exam</h2>
                        <form onSubmit={handleCreate}>
                            <div className="form-group">
                                <label>Exam Name *</label>
                                <input type="text" value={newExam.name} onChange={(e) => setNewExam({ ...newExam, name: e.target.value })} placeholder="e.g., CA Final - Direct Tax" required />
                            </div>
                            <div className="form-group">
                                <label>Subject</label>
                                <input type="text" value={newExam.subject} onChange={(e) => setNewExam({ ...newExam, subject: e.target.value })} placeholder="e.g., Taxation" />
                            </div>
                            <div className="form-group">
                                <label>Exam Date</label>
                                <input type="date" value={newExam.examDate} onChange={(e) => setNewExam({ ...newExam, examDate: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label>Solution PDF *</label>
                                <input type="file" accept=".pdf" onChange={(e) => setNewExam({ ...newExam, solutionPdf: e.target.files[0] })} required />
                                <p className="help-text">Upload the solution PDF to extract questions and model answers.</p>
                            </div>
                            <div className="modal-actions">
                                <button type="button" onClick={() => setShowCreate(false)} className="cancel-btn">Cancel</button>
                                <button type="submit" className="submit-btn" disabled={creating}>{creating ? 'Creating…' : 'Create Exam'}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* CHECKED PAPERS TAB (renamed from Edit Checked Copy)                        */
/* ══════════════════════════════════════════════════════════════════════════ */

function JobCard({ job, navigate, onRecheckDone, onRemove }) {
    const [isRechecking, setIsRechecking] = useState(false);
    const [recheckError, setRecheckError] = useState(null);
    const [recheckDone,  setRecheckDone]  = useState(false);
    const [removing,     setRemoving]     = useState(false);
    const [deleting,     setDeleting]     = useState(false);
    const pollRef = useRef(null);

    const clearPoll = () => { if (pollRef.current) clearInterval(pollRef.current); };
    useEffect(() => () => clearPoll(), []);

    const handleRecheck = async (e) => {
        e.stopPropagation();
        setIsRechecking(true);
        setRecheckError(null);
        try {
            await recheckPipeline(job.task_id);
            pollRef.current = setInterval(async () => {
                try {
                    const s = await getPipelineStatus(job.task_id);
                    if (s.stage === 'completed' || s.status === 'done') {
                        clearPoll();
                        setIsRechecking(false);
                        setRecheckDone(true);
                        onRecheckDone();
                    } else if (s.stage === 'recheck_failed' || s.status === 'failed') {
                        clearPoll();
                        setIsRechecking(false);
                        setRecheckError(s.error || 'Recheck failed.');
                    }
                } catch (_) {}
            }, 3000);
        } catch (err) {
            setIsRechecking(false);
            setRecheckError(err.response?.data?.detail || err.message);
        }
    };

    const handleRemove = async (e) => {
        e.stopPropagation();
        if (!confirm(`Remove "${job.student_name}" from the queue?`)) return;
        setRemoving(true);
        try {
            await removeFromQueue(job.task_id);
            onRemove();
        } catch (err) {
            alert('Could not remove: ' + (err.response?.data?.detail || err.message));
            setRemoving(false);
        }
    };

    const handleDelete = async (e) => {
        e.stopPropagation();
        if (!confirm(`Permanently delete the result for "${job.student_name}"? This cannot be undone.`)) return;
        setDeleting(true);
        try {
            await removeFromQueue(job.task_id);
            onRemove();
        } catch (err) {
            alert('Could not delete: ' + (err.response?.data?.detail || err.message));
            setDeleting(false);
        }
    };

    const canRecheck = job.grading_ready && !job.checked_copy_available && !recheckDone;
    const isQueued   = job.status === 'queued';
    const isRunning  = job.status === 'running';
    const isPaused   = job.status === 'paused';

    return (
        <div
            className={`job-card ${job.status}`}
            onClick={() => {
                if (job.checked_copy_available || recheckDone)
                    navigate(`/checked-paper/${job.task_id}`);
            }}
            style={{ cursor: (job.checked_copy_available || recheckDone) ? 'pointer' : 'default' }}
        >
            <div className="job-card-header">
                <span className="job-student-icon">
                    {isRunning ? '⚙️' : isQueued ? '⏳' : isPaused ? '⚠️' : '👤'}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <h3 className="job-student-name">{job.student_name || 'Unknown Student'}</h3>
                    {job.paper_label && (
                        <span style={{ fontSize: '12px', color: '#72767d' }}>{job.paper_label}</span>
                    )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                    {isQueued && job.queue_position > 0 && (
                        <span style={{
                            background: '#5865f2', color: '#fff',
                            borderRadius: '20px', padding: '2px 10px', fontSize: '11px', fontWeight: 700,
                        }}>#{job.queue_position} in queue</span>
                    )}
                    {isRunning && (
                        <span style={{
                            background: '#23a559', color: '#fff',
                            borderRadius: '20px', padding: '2px 10px', fontSize: '11px', fontWeight: 700,
                            animation: 'pulse 1.5s infinite',
                        }}>⚙️ Running</span>
                    )}
                    <span className={`job-status-badge ${job.status}`}>{job.status}</span>
                </div>
            </div>

            {/* Score row — only for completed papers */}
            {!isQueued && !isRunning && (
                <div className="job-score-row">
                    <span className="job-score-lbl">Score:</span>
                    <span className="job-score-val">
                        {job.total_possible > 0
                            ? `${job.total_obtained.toFixed(1)} / ${job.total_possible.toFixed(1)}`
                            : 'Pending'
                        }
                    </span>
                    {job.total_possible > 0 && (
                        <span className="job-score-pct">({job.percentage.toFixed(1)}%)</span>
                    )}
                </div>
            )}

            {/* Queued paper info */}
            {isQueued && job.queued_at && (
                <div style={{ fontSize: '12px', color: '#72767d', padding: '4px 0' }}>
                    Queued {Math.round((Date.now() / 1000 - job.queued_at) / 60)} min ago
                </div>
            )}

            {/* Running spinner */}
            {isRunning && (
                <div style={{ fontSize: '12px', color: '#23a559', padding: '4px 0', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#23a559', animation: 'pulse 1.5s infinite' }} />
                    Checking in progress…
                </div>
            )}

            <div className="job-card-footer">
                <span className="job-date">
                    {new Date(job.created_at * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </span>
                <div className="job-card-actions" onClick={(e) => e.stopPropagation()}>
                    {/* Remove from queue button */}
                    {isQueued && (
                        <button
                            type="button"
                            className="reset-btn"
                            onClick={handleRemove}
                            disabled={removing}
                            title="Remove from queue"
                            style={{ padding: '4px 10px', fontSize: '12px', background: '#ed4245', borderColor: '#ed4245', color: '#fff' }}
                        >
                            {removing ? '⏳' : '✕ Remove'}
                        </button>
                    )}

                    {/* Recheck button */}
                    {canRecheck && (
                        <button
                            type="button"
                            className="recheck-btn"
                            onClick={handleRecheck}
                            disabled={isRechecking}
                            title="Re-run Stage 7 to generate the checked copy (no re-grading, no API cost)"
                        >
                            {isRechecking ? '⏳ Generating…' : '🔄 Retry Checked Copy'}
                        </button>
                    )}
                    {recheckDone && (
                        <span className="recheck-success">✅ Checked copy ready</span>
                    )}
                    {recheckError && (
                        <span className="recheck-error-msg" title={recheckError}>⚠️ Retry failed</span>
                    )}

                    {/* View & Download button */}
                    {(job.checked_copy_available || recheckDone) && (
                        <button
                            type="button"
                            className="edit-copy-btn"
                            style={{ background: '#5865f2', borderColor: '#5865f2' }}
                            onClick={(e) => {
                                e.stopPropagation();
                                navigate(`/checked-paper/${job.task_id}`);
                            }}
                        >
                            📥 View & Download
                        </button>
                    )}

                    {/* Edit button */}
                    {(job.checked_copy_available || recheckDone) && (
                        <button
                            type="button"
                            className="edit-copy-btn"
                            onClick={(e) => {
                                e.stopPropagation();
                                navigate(`/checked-paper/${job.task_id}/edit`);
                            }}
                        >
                            ✏️ Edit Copy
                        </button>
                    )}

                    {/* Delete button — for completed/failed jobs */}
                    {!isQueued && !isRunning && (
                        <button
                            type="button"
                            onClick={handleDelete}
                            disabled={deleting}
                            title="Permanently delete this result"
                            style={{
                                padding: '4px 10px', fontSize: '12px',
                                background: 'transparent', border: '1px solid #4f545c',
                                color: '#72767d', borderRadius: '6px', cursor: 'pointer',
                                transition: 'background 0.2s, color 0.2s, border-color 0.2s',
                            }}
                            onMouseEnter={e => { e.currentTarget.style.background = '#ed4245'; e.currentTarget.style.color = '#fff'; e.currentTarget.style.borderColor = '#ed4245'; }}
                            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#72767d'; e.currentTarget.style.borderColor = '#4f545c'; }}
                        >
                            {deleting ? '⏳' : '🗑️'}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
}

function CheckedPapersTab() {
    const navigate = useNavigate();
    const [jobs,        setJobs]        = useState([]);
    const [queuePaused, setQueuePaused] = useState(false);
    const [loading,     setLoading]     = useState(true);
    const [filter,      setFilter]      = useState('');
    const [pauseLoading, setPauseLoading] = useState(false);

    const loadJobs = useCallback(async () => {
        try {
            const res = await getPipelineJobs();
            // Backend returns { jobs: [...], queue_paused: bool }
            if (res && Array.isArray(res.jobs)) {
                setJobs(res.jobs);
                setQueuePaused(res.queue_paused || false);
            } else if (Array.isArray(res)) {
                // Fallback: old API shape
                setJobs(res);
            }
        } catch (err) {
            console.error('Failed to load checked papers:', err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadJobs();
        const iv = setInterval(loadJobs, 5000);
        return () => clearInterval(iv);
    }, [loadJobs]);

    const handlePauseToggle = async () => {
        setPauseLoading(true);
        try {
            if (queuePaused) {
                await resumeQueue();
                setQueuePaused(false);
            } else {
                await pauseQueue();
                setQueuePaused(true);
            }
        } catch (err) {
            alert('Failed: ' + (err.response?.data?.detail || err.message));
        } finally {
            setPauseLoading(false);
        }
    };

    const filteredJobs = jobs.filter(j =>
        (j.student_name || '').toLowerCase().includes(filter.toLowerCase()) ||
        (j.paper_label  || '').toLowerCase().includes(filter.toLowerCase()) ||
        j.task_id.toLowerCase().includes(filter.toLowerCase())
    );

    const inProgressJobs = filteredJobs.filter(j => j.status === 'queued' || j.status === 'running');
    const pausedJobs     = filteredJobs.filter(j => j.status === 'paused');
    const completedJobs  = filteredJobs.filter(j => j.status === 'completed' || j.status === 'done');
    const failedJobs     = filteredJobs.filter(j => j.status === 'failed');

    const hasActiveQueue = inProgressJobs.length > 0;

    return (
        <div className="edit-checked-tab">
            <div className="tab-header-row">
                <div>
                    <h2 className="tab-section-title">Checked Papers</h2>
                    <p className="tab-section-desc">All papers — queued, in progress, and completed. Click a completed paper to view, download, or edit.</p>
                </div>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
                    {hasActiveQueue && (
                        <button
                            type="button"
                            className={queuePaused ? 'run-btn' : 'reset-btn'}
                            onClick={handlePauseToggle}
                            disabled={pauseLoading}
                            style={{ padding: '8px 16px', fontSize: '13px', margin: 0, width: 'auto' }}
                        >
                            {pauseLoading ? '⏳' : queuePaused ? '▶ Resume Queue' : '⏸ Pause Queue'}
                        </button>
                    )}
                    <div className="search-box">
                        <input
                            type="text"
                            placeholder="Search student or paper…"
                            value={filter}
                            onChange={(e) => setFilter(e.target.value)}
                            className="search-input"
                        />
                    </div>
                </div>
            </div>

            {queuePaused && (
                <div style={{ background: '#fef3c7', border: '1px solid #f59e0b', borderRadius: '8px', padding: '10px 16px', marginBottom: '16px', color: '#92400e', fontWeight: 600 }}>
                    ⏸ Queue is paused — new papers will wait until you resume.
                </div>
            )}

            {loading ? (
                <div className="loading">Loading checked papers…</div>
            ) : (
                <>
                    {/* IN PROGRESS section */}
                    {inProgressJobs.length > 0 && (
                        <div style={{ marginBottom: '24px' }}>
                            <h3 style={{ color: '#b5bac1', fontSize: '13px', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '12px', fontWeight: 600 }}>
                                🔄 In Progress ({inProgressJobs.length})
                            </h3>
                            <div className="jobs-grid">
                                {inProgressJobs.map(job => (
                                    <JobCard key={job.task_id} job={job} navigate={navigate} onRecheckDone={loadJobs} onRemove={loadJobs} />
                                ))}
                            </div>
                        </div>
                    )}

                    {/* PAUSED section */}
                    {pausedJobs.length > 0 && (
                        <div style={{ marginBottom: '24px' }}>
                            <h3 style={{ color: '#f59e0b', fontSize: '13px', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '12px', fontWeight: 600 }}>
                                ⚠️ Paused — Waiting for Action ({pausedJobs.length})
                            </h3>
                            <div className="jobs-grid">
                                {pausedJobs.map(job => (
                                    <JobCard key={job.task_id} job={job} navigate={navigate} onRecheckDone={loadJobs} onRemove={loadJobs} />
                                ))}
                            </div>
                        </div>
                    )}

                    {/* FAILED section */}
                    {failedJobs.length > 0 && (
                        <div style={{ marginBottom: '24px' }}>
                            <h3 style={{ color: '#ed4245', fontSize: '13px', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '12px', fontWeight: 600 }}>
                                ❌ Failed ({failedJobs.length})
                            </h3>
                            <div className="jobs-grid">
                                {failedJobs.map(job => (
                                    <JobCard key={job.task_id} job={job} navigate={navigate} onRecheckDone={loadJobs} onRemove={loadJobs} />
                                ))}
                            </div>
                        </div>
                    )}

                    {/* COMPLETED section */}
                    {completedJobs.length > 0 ? (
                        <div style={{ marginBottom: '24px' }}>
                            <h3 style={{ color: '#23a559', fontSize: '13px', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '12px', fontWeight: 600 }}>
                                ✅ Completed ({completedJobs.length})
                            </h3>
                            <div className="jobs-grid">
                                {completedJobs.map(job => (
                                    <JobCard key={job.task_id} job={job} navigate={navigate} onRecheckDone={loadJobs} onRemove={loadJobs} />
                                ))}
                            </div>
                        </div>
                    ) : (
                        !inProgressJobs.length && !pausedJobs.length && !failedJobs.length && (
                            <div className="empty-state">
                                <div className="empty-icon">📝</div>
                                <h3>No checked papers yet</h3>
                                <p>{filter ? 'No papers match your search' : 'Queue a paper using Old or New Papers pipeline'}</p>
                            </div>
                        )
                    )}
                </>
            )}
        </div>
    );
}


/* ══════════════════════════════════════════════════════════════════════════ */
/* DASHBOARD ROOT                                                              */
/* ══════════════════════════════════════════════════════════════════════════ */

const TABS = [
    { id: 'new',            label: '⚡ New Papers Checking',   desc: 'Pre-built JSON paper + student sheet' },
    { id: 'old',            label: '📜 Old Papers Checking',   desc: 'QP + Solution + student sheet' },
    { id: 'checked_papers', label: '📋 Checked Papers',        desc: 'All papers — queued, running, done' },
    { id: 'feedback',       label: '💬 Feedback Only',         desc: 'Manual marking + feedback' },
    { id: 'exams',          label: '🗂 Manage Exams',           desc: 'Exam & student management' },
];

function Dashboard() {
    const { user, logout } = useAuth();
    const navigate         = useNavigate();
    const location         = useLocation();

    // Read ?tab= param from URL to support deep-linking (e.g. /?tab=checked from Back button)
    const TAB_MAP = { checked: 'checked_papers', old: 'old', new: 'new', feedback: 'feedback', exams: 'exams' };
    const initialTab = (() => {
        const param = new URLSearchParams(location.search).get('tab');
        return TAB_MAP[param] || 'new';
    })();
    const [activeTab, setActiveTab] = useState(initialTab);

    return (
        <div className="dashboard">
            <header className="header">
                <div className="header-left">
                    <span className="logo-icon">🎓</span>
                    <h1>CheckerAI</h1>
                    <span className="module-indicator checker-indicator">✓ Checker</span>
                </div>
                <div className="header-right">
                    <button onClick={() => navigate('/setter')}  className="setter-btn">📝 SetterAI</button>
                    <button onClick={() => navigate('/mentor')}  className="mentor-btn">👨‍🏫 MentorAI</button>
                    <span className="user-name">{user?.name || user?.email}</span>
                    <button onClick={logout} className="logout-btn">Logout</button>
                </div>
            </header>

            <main className="main-content">
                {/* Tab bar */}
                <div className="tab-bar">
                    {TABS.map(tab => (
                        <button
                            key={tab.id}
                            id={`tab-${tab.id}`}
                            className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
                            onClick={() => setActiveTab(tab.id)}
                        >
                            <span className="tab-label">{tab.label}</span>
                            <span className="tab-desc">{tab.desc}</span>
                        </button>
                    ))}
                </div>

                {/* Tab content */}
                <div className="tab-content">
                    {activeTab === 'old'            && <OldPapersTab />}
                    {activeTab === 'new'            && <NewPapersTab />}
                    {activeTab === 'checked_papers' && <CheckedPapersTab />}
                    {activeTab === 'feedback'       && <FeedbackTab />}
                    {activeTab === 'exams'          && <ExamsTab />}
                </div>
            </main>
        </div>
    );
}

export default Dashboard;
