import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../App';
import {
    getExams, createExam, deleteExam,
    getPaperCatalog,
    runOldPipeline, runNewPipeline, runFeedbackPipeline,
    getPipelineStatus, downloadPipelineResult,
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
    started:    'Starting pipeline…',
    stage_1:    'Stage 1 — Extracting question schema',
    stage_1_2:  'Stage 1+2 — Building schema from paper JSON',
    stage_2:    'Stage 2 — Extracting model answers',
    stage_3:    'Stage 3 — Running OCR on student answer sheet',
    stage_4:    'Stage 4 — Aligning answers',
    stage_5:    'Stage 5 — Grading with Claude',
    stage_6:    'Stage 6 — Generating PDF report',
    stage_7:    'Stage 7 — Annotating checked copy',
    completed:  'Complete!',
    failed:     'Failed',
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
                <div className="result-pct">{meta.percentage}%</div>
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
/* OLD PAPERS TAB                                                             */
/* ══════════════════════════════════════════════════════════════════════════ */

function OldPapersTab() {
    const navigate = useNavigate();
    const [form, setForm]     = useState({ studentName: '', qpPdf: null, saPdf: null, asPdf: null });
    const [taskId, setTaskId] = useState(null);
    const [status, setStatus] = useState(null);
    const [running, setRunning] = useState(false);
    const pollRef = useRef(null);

    const clearPoll = () => { if (pollRef.current) clearInterval(pollRef.current); };

    useEffect(() => () => clearPoll(), []);

    const startPolling = useCallback((tid) => {
        pollRef.current = setInterval(async () => {
            try {
                const s = await getPipelineStatus(tid);
                setStatus(s);
                if (s.status === 'done' || s.stage === 'completed' || s.status === 'failed') {
                    clearPoll();
                    setRunning(false);
                }
            } catch (_) {}
        }, 3000);
    }, []);

    const [errorMsg, setErrorMsg] = useState(null);


    const handleSubmit = async (e) => {
        e.preventDefault();
        setErrorMsg(null);
        const { qpPdf, saPdf, asPdf } = form;
        if (!qpPdf || !saPdf || !asPdf) {
            setErrorMsg('Please provide all three PDFs (Question, Solution, Student).');
            return;
        }
        setRunning(true);
        setStatus({ stage: 'started', message: 'Submitting…', status: 'queued' });
        try {
            const res = await runOldPipeline(form.studentName, qpPdf, saPdf, asPdf);
            setTaskId(res.task_id);
            startPolling(res.task_id);
        } catch (err) {
            setRunning(false);
            setStatus({ stage: 'failed', error: err.response?.data?.detail || err.message, status: 'failed' });
        }
    };

    const reset = () => {
        clearPoll();
        setTaskId(null);
        setStatus(null);
        setRunning(false);
        setForm({ studentName: '', qpPdf: null, saPdf: null, asPdf: null });
    };

    const isDone = status?.stage === 'completed' || status?.status === 'done';
    const isFailed = status?.stage === 'failed' || status?.status === 'failed' || errorMsg;

    if (isDone) {
        return (
            <ResultCard
                status={status}
                taskId={taskId}
                studentName={form.studentName}
                onReset={reset}
                navigate={navigate}
            />
        );
    }

    return (
        <form className="pipeline-form" onSubmit={handleSubmit}>
            <p className="pipeline-desc">
                Provide all three documents. Claude AI will extract the schema from the question
                paper, model answers from the solution, OCR the student sheet, align answers,
                grade, and produce an annotated checked copy.
            </p>

            <div className="form-field">
                <label className="field-lbl" htmlFor="old-student-name">Student Name (Optional)</label>
                <input
                    id="old-student-name"
                    className="text-input"
                    type="text"
                    placeholder="e.g. Rahul Sharma"
                    value={form.studentName}
                    onChange={(e) => setForm({ ...form, studentName: e.target.value })}
                    disabled={running}
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

            {running && status && (
                <div className="pipeline-progress">
                    <ProgressBar stage={status.stage} />
                    <p className="progress-msg">
                        {STAGE_LABELS[status.stage] || status.message || 'Working…'}
                    </p>
                </div>
            )}

            {isFailed && (
                <div className="pipeline-error">
                    ⚠️ {errorMsg || status?.error || 'Pipeline failed. Please try again.'}
                    <button type="button" className="reset-btn" onClick={reset}>Reset</button>
                </div>
            )}

            {!running && (
                <button id="old-run-btn" type="submit" className="run-btn">
                    🚀 Run Old Papers Pipeline
                </button>
            )}
        </form>
    );
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* NEW PAPERS TAB                                                             */
/* ══════════════════════════════════════════════════════════════════════════ */

function NewPapersTab() {
    const navigate  = useNavigate();
    const [catalog, setCatalog] = useState(null);
    const [sel,     setSel]     = useState({ exam: '', subject: '', type: '', paper: '' });
    const [form,    setForm]    = useState({ studentName: '', asPdf: null });
    const [taskId,  setTaskId]  = useState(null);
    const [status,  setStatus]  = useState(null);
    const [running, setRunning] = useState(false);
    const [errorMsg, setErrorMsg] = useState(null);
    const pollRef = useRef(null);

    const clearPoll = () => { if (pollRef.current) clearInterval(pollRef.current); };
    useEffect(() => () => clearPoll(), []);

    useEffect(() => {
        getPaperCatalog().then(setCatalog).catch(console.error);
    }, []);

    const exams    = catalog ? Object.keys(catalog).sort() : [];
    const subjects = sel.exam && catalog?.[sel.exam] ? Object.keys(catalog[sel.exam]).sort() : [];
    const types    = sel.subject && catalog?.[sel.exam]?.[sel.subject]
        ? Object.entries(catalog[sel.exam][sel.subject])
              .filter(([, arr]) => arr.length > 0)
              .map(([t]) => t)
        : [];
    const papers   = (sel.type && catalog?.[sel.exam]?.[sel.subject]?.[sel.type]) || [];

    const selectedPaperPath = papers.find(p => p.filename === sel.paper)?.path || '';

    const startPolling = useCallback((tid) => {
        pollRef.current = setInterval(async () => {
            try {
                const s = await getPipelineStatus(tid);
                setStatus(s);
                if (s.status === 'done' || s.stage === 'completed' || s.status === 'failed') {
                    clearPoll();
                    setRunning(false);
                }
            } catch (_) {}
        }, 3000);
    }, []);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setErrorMsg(null);
        if (!selectedPaperPath || !form.asPdf) {
            setErrorMsg('Please select a paper and provide the student answer sheet.');
            return;
        }
        setRunning(true);
        setStatus({ stage: 'started', message: 'Submitting…', status: 'queued' });
        try {
            const res = await runNewPipeline(form.studentName, selectedPaperPath, form.asPdf);
            setTaskId(res.task_id);
            startPolling(res.task_id);
        } catch (err) {
            setRunning(false);
            setStatus({ stage: 'failed', error: err.response?.data?.detail || err.message, status: 'failed' });
        }
    };

    const reset = () => {
        clearPoll();
        setTaskId(null);
        setStatus(null);
        setRunning(false);
        setForm({ studentName: '', asPdf: null });
        setSel({ exam: '', subject: '', type: '', paper: '' });
    };

    const isDone   = status?.stage === 'completed' || status?.status === 'done';
    const isFailed = status?.stage === 'failed'    || status?.status === 'failed' || errorMsg;

    if (isDone) {
        return (
            <ResultCard
                status={status}
                taskId={taskId}
                studentName={form.studentName}
                onReset={reset}
                navigate={navigate}
            />
        );
    }

    return (
        <form className="pipeline-form" onSubmit={handleSubmit}>
            <p className="pipeline-desc">
                Select a pre-built paper from our library, upload the student answer sheet,
                and the FT pipeline will handle OCR, sub-part alignment, grading, and
                the annotated checked copy automatically.
            </p>

            <div className="form-field">
                <label className="field-lbl" htmlFor="new-student-name">Student Name (Optional)</label>
                <input
                    id="new-student-name"
                    className="text-input"
                    type="text"
                    placeholder="e.g. Priya Mehta"
                    value={form.studentName}
                    onChange={(e) => setForm({ ...form, studentName: e.target.value })}
                    disabled={running}
                />
            </div>

            {/* Cascading dropdowns */}
            <div className="cascade-grid">
                <div className="form-field">
                    <label className="field-lbl" htmlFor="dd-exam">Exam Level *</label>
                    <select
                        id="dd-exam"
                        className="select-input"
                        value={sel.exam}
                        onChange={(e) => setSel({ exam: e.target.value, subject: '', type: '', paper: '' })}
                        disabled={running || !catalog}
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
                        disabled={running || !sel.exam}
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
                        disabled={running || !sel.subject}
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
                        disabled={running || !sel.type}
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

            {running && status && (
                <div className="pipeline-progress">
                    <ProgressBar stage={status.stage} />
                    <p className="progress-msg">
                        {STAGE_LABELS[status.stage] || status.message || 'Working…'}
                    </p>
                </div>
            )}

            {isFailed && (
                <div className="pipeline-error">
                    ⚠️ {errorMsg || status?.error || 'Pipeline failed. Please try again.'}
                    <button type="button" className="reset-btn" onClick={reset}>Reset</button>
                </div>
            )}

            {!running && (
                <button id="new-run-btn" type="submit" className="run-btn" disabled={!selectedPaperPath}>
                    🚀 Run New Papers Pipeline
                </button>
            )}
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
/* DASHBOARD ROOT                                                              */
/* ══════════════════════════════════════════════════════════════════════════ */

const TABS = [
    { id: 'new',   label: '⚡ New Papers Checking',  desc: 'Pre-built JSON paper + student sheet' },
    { id: 'old',   label: '📜 Old Papers Checking',  desc: 'QP + Solution + student sheet' },
    { id: 'feedback', label: '💬 Feedback Only',    desc: 'Manual marking + feedback' },
    { id: 'exams', label: '📋 Manage Exams',          desc: 'Exam & student management' },
];

function Dashboard() {
    const { user, logout } = useAuth();
    const navigate         = useNavigate();
    const [activeTab, setActiveTab] = useState('new');

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
                    {activeTab === 'old'   && <OldPapersTab />}
                    {activeTab === 'new'   && <NewPapersTab />}
                    {activeTab === 'feedback' && <FeedbackTab />}
                    {activeTab === 'exams' && <ExamsTab />}
                </div>
            </main>
        </div>
    );
}

export default Dashboard;
