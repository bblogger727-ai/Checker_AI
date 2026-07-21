import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getStudent, getAnnotationManifest, patchCheckedCopy } from '../services/api';
import './EditCheckedCopy.css';

/* ── Helpers ─────────────────────────────────────────────────────────────── */

function saveBlob(blob, filename) {
    const url = window.URL.createObjectURL(blob);
    const a   = document.createElement('a');
    a.href     = url;
    a.download = filename;
    a.click();
    window.URL.revokeObjectURL(url);
}

function fmtNum(v) {
    const n = parseFloat(v);
    return isNaN(n) ? v : (n === Math.floor(n) ? String(Math.floor(n)) : n.toFixed(1));
}

/* ── UI Components ───────────────────────────────────────────────────────── */

function DPad({ onMove }) {
    return (
        <div className="dpad-container">
            <button className="dpad-btn up" onClick={() => onMove('up')}>▲</button>
            <div className="dpad-middle">
                <button className="dpad-btn left" onClick={() => onMove('left')}>◀</button>
                <div className="dpad-center"></div>
                <button className="dpad-btn right" onClick={() => onMove('right')}>▶</button>
            </div>
            <button className="dpad-btn down" onClick={() => onMove('down')}>▼</button>
        </div>
    );
}

function SectionToolbar({ mode, setMode }) {
    return (
        <div className="section-toolbar">
            <button className={`tool-btn ${mode === 'edit' ? 'active' : ''}`} onClick={() => setMode('edit')}>✏️ Edit</button>
            <button className={`tool-btn ${mode === 'move' ? 'active' : ''}`} onClick={() => setMode('move')}>✥ Move</button>
            <button className={`tool-btn ${mode === 'remove' ? 'active' : ''}`} onClick={() => setMode('remove')}>🗑 Remove</button>
        </div>
    );
}

/* ── Sub-component: Question Editor Card ─────────────────────────────────── */

function QuestionCard({ 
    mkey, question, changes, 
    onChangeMarks, onChangeFeedback, onChangeTickCross,
    onDeleteTickCross, onRemoveStamp, onMoveStamp, onMoveFeedback, onMoveTick
}) {
    const qChanges    = changes[mkey] || {};
    const curObtained = qChanges.marks_obtained !== undefined ? qChanges.marks_obtained : question.marks_obtained;
    const curTotal    = qChanges.marks_total !== undefined ? qChanges.marks_total : question.marks_total;
    const curFeedback = qChanges.feedback_text !== undefined ? qChanges.feedback_text : (question.feedback_text || '');
    const isStampRemoved = qChanges.remove_stamp || false;
    const isFbRemoved    = qChanges.feedback_text === "" || (!curFeedback && qChanges.feedback_text !== undefined);

    const deletedSet = new Set(qChanges.delete_tick_indices || []);
    const isDirty = Object.keys(qChanges).length > 0;
    const ratio   = curTotal > 0 ? curObtained / curTotal : 0;
    const pct     = Math.round(ratio * 100);

    const [marksMode, setMarksMode] = useState('edit');
    const [fbMode, setFbMode] = useState('edit');

    // TC Modes
    const [tcModes, setTcModes] = useState({});
    const setTcMode = (idx, mode) => setTcModes(prev => ({...prev, [idx]: mode}));

    return (
        <div className={`qcard ${isDirty ? 'qcard--dirty' : ''}`}>
            <div className="qcard-header">
                <div className="qcard-title">
                    <span className="qcard-name">{question.display_name}</span>
                    {isDirty && <span className="dirty-badge">Edited</span>}
                </div>
                <div className="qcard-score">
                    <span className="score-pill" style={{
                        background: ratio >= 1 ? '#c6f6d5' : ratio >= 0.5 ? '#fef3c7' : '#fed7d7',
                        color:      ratio >= 1 ? '#22543d' : ratio >= 0.5 ? '#92400e' : '#c53030',
                    }}>
                        {fmtNum(curObtained)} / {fmtNum(curTotal)}
                    </span>
                    <span className="score-pct">{pct}%</span>
                </div>
            </div>

            {/* MARKS SECTION */}
            <div className="qcard-section">
                <div className="section-header">
                    <label className="field-label">Marks Stamp</label>
                    <SectionToolbar mode={marksMode} setMode={setMarksMode} />
                </div>
                
                {marksMode === 'edit' && (
                    <div className="marks-row">
                        {isStampRemoved ? (
                            <div className="removed-placeholder">Marks stamp is marked for removal. Undo in Remove tab to edit.</div>
                        ) : (
                            <>
                                <div className="marks-field">
                                    <span className="marks-hint">Obtained</span>
                                    <input
                                        type="number" min="0" max={curTotal} step="0.5"
                                        value={curObtained}
                                        onChange={e => onChangeMarks(mkey, 'marks_obtained', parseFloat(e.target.value))}
                                        className="marks-input"
                                    />
                                </div>
                                <span className="marks-sep">/</span>
                                <div className="marks-field">
                                    <span className="marks-hint">Total</span>
                                    <input
                                        type="number" min="0" step="0.5"
                                        value={curTotal}
                                        onChange={e => onChangeMarks(mkey, 'marks_total', parseFloat(e.target.value))}
                                        className="marks-input"
                                    />
                                </div>
                            </>
                        )}
                    </div>
                )}
                {marksMode === 'move' && (
                    <div className="move-panel">
                        {isStampRemoved ? (
                            <div className="removed-placeholder">Marks stamp is marked for removal.</div>
                        ) : (
                            <>
                                <span className="move-hint">Move the stamp by 30px increments:</span>
                                <DPad onMove={(dir) => onMoveStamp(mkey, dir)} />
                                <div className="move-stats">
                                    Net movement: 
                                    Up: {(qChanges.move_stamp?.up || 0)} | Down: {(qChanges.move_stamp?.down || 0)} | 
                                    Left: {(qChanges.move_stamp?.left || 0)} | Right: {(qChanges.move_stamp?.right || 0)}
                                </div>
                            </>
                        )}
                    </div>
                )}
                {marksMode === 'remove' && (
                    <div className="remove-panel">
                        {isStampRemoved ? (
                            <>
                                <span className="tc-deleted-badge">🗑 Marks stamp marked for removal</span>
                                <button className="tc-btn tc-undo-btn" onClick={() => onRemoveStamp(mkey, false)}>Undo Remove</button>
                            </>
                        ) : (
                            <button className="remove-action-btn" onClick={() => onRemoveStamp(mkey, true)}>Remove Marks Stamp from PDF</button>
                        )}
                    </div>
                )}
            </div>

            {/* FEEDBACK SECTION */}
            <div className="qcard-section">
                <div className="section-header">
                    <label className="field-label">Feedback Comment</label>
                    <SectionToolbar mode={fbMode} setMode={setFbMode} />
                </div>
                
                {fbMode === 'edit' && (
                    <div className="feedback-row">
                        {isFbRemoved ? (
                            <div className="removed-placeholder">Feedback is marked for removal. Undo in Remove tab to edit.</div>
                        ) : (
                            <textarea
                                rows={2}
                                placeholder={question.has_feedback ? question.feedback_text : 'No feedback — type here to add one'}
                                value={curFeedback}
                                onChange={e => onChangeFeedback(mkey, e.target.value)}
                                className="fb-textarea"
                            />
                        )}
                    </div>
                )}
                {fbMode === 'move' && (
                    <div className="move-panel">
                        {isFbRemoved ? (
                            <div className="removed-placeholder">Feedback is marked for removal.</div>
                        ) : (
                            <>
                                <span className="move-hint">Move the feedback by 30px increments:</span>
                                <DPad onMove={(dir) => onMoveFeedback(mkey, dir)} />
                                <div className="move-stats">
                                    Net movement: 
                                    Up: {(qChanges.move_feedback?.up || 0)} | Down: {(qChanges.move_feedback?.down || 0)} | 
                                    Left: {(qChanges.move_feedback?.left || 0)} | Right: {(qChanges.move_feedback?.right || 0)}
                                </div>
                            </>
                        )}
                    </div>
                )}
                {fbMode === 'remove' && (
                    <div className="remove-panel">
                        {isFbRemoved ? (
                            <>
                                <span className="tc-deleted-badge">🗑 Feedback marked for removal</span>
                                <button className="tc-btn tc-undo-btn" onClick={() => onChangeFeedback(mkey, question.feedback_text || "Restored feedback")}>Undo Remove</button>
                            </>
                        ) : (
                            <button className="remove-action-btn" onClick={() => onChangeFeedback(mkey, "")}>Remove Feedback from PDF</button>
                        )}
                    </div>
                )}
            </div>

            {/* ANNOTATIONS SECTION */}
            {question.ticks_crosses && question.ticks_crosses.length > 0 && (
                <div className="qcard-section">
                    <label className="field-label" style={{marginBottom: '10px', display: 'block'}}>Ticks &amp; Crosses</label>
                    <div className="tc-list">
                        {question.ticks_crosses.map((tc, i) => {
                            const tcChanges = (qChanges.ticks_crosses || []).find(c => c.index === i);
                            const curAction = tcChanges ? tcChanges.action : tc.action;
                            const isDeleted = deletedSet.has(i);
                            const tMode = tcModes[i] || 'edit';
                            const tcMoves = qChanges.move_tick_indices?.[i] || {up:0, down:0, left:0, right:0};
                            
                            return (
                                <div key={i} className={`tc-row-advanced ${isDeleted ? 'tc-row--deleted' : ''}`}>
                                    <div className="tc-adv-header">
                                        <span className="tc-label">Pg {tc.page} · #{i + 1} ({curAction})</span>
                                        {!isDeleted && <SectionToolbar mode={tMode} setMode={(m) => setTcMode(i, m)} />}
                                    </div>
                                    
                                    <div className="tc-adv-body">
                                        {isDeleted ? (
                                            <div className="remove-panel">
                                                <span className="tc-deleted-badge">🗑 Marked for removal</span>
                                                <button className="tc-btn tc-undo-btn" onClick={() => onDeleteTickCross(mkey, i, false)}>Undo Remove</button>
                                            </div>
                                        ) : (
                                            <>
                                                {tMode === 'edit' && (
                                                    <div className="tc-toggle">
                                                        <button
                                                            className={`tc-btn tick-btn ${curAction === 'tick' ? 'active' : ''}`}
                                                            onClick={() => onChangeTickCross(mkey, i, 'tick')}
                                                        >✓ Tick</button>
                                                        <button
                                                            className={`tc-btn cross-btn ${curAction === 'cross' ? 'active' : ''}`}
                                                            onClick={() => onChangeTickCross(mkey, i, 'cross')}
                                                        >✗ Cross</button>
                                                    </div>
                                                )}
                                                {tMode === 'move' && (
                                                    <div className="move-panel move-panel-small">
                                                        <DPad onMove={(dir) => onMoveTick(mkey, i, dir)} />
                                                        <div className="move-stats-small">
                                                            ΔU: {tcMoves.up} | ΔD: {tcMoves.down} | ΔL: {tcMoves.left} | ΔR: {tcMoves.right}
                                                        </div>
                                                    </div>
                                                )}
                                                {tMode === 'remove' && (
                                                    <div className="remove-panel">
                                                        <button className="remove-action-btn" onClick={() => onDeleteTickCross(mkey, i, true)}>Remove Annotation</button>
                                                    </div>
                                                )}
                                            </>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}

/* ── Main Page ──────────────────────────────────────────────────────────── */

function EditCheckedCopy() {
    const { id }     = useParams();
    const navigate   = useNavigate();

    const [student,    setStudent]    = useState(null);
    const [manifest,   setManifest]   = useState(null);
    const [changes,    setChanges]    = useState({});
    const [loading,    setLoading]    = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [error,      setError]      = useState('');
    const [toast,      setToast]      = useState('');

    /* ── Data load ──────────────────────────────────────────────────────── */

    useEffect(() => {
        async function load() {
            setLoading(true);
            try {
                const [studentData, manifestData] = await Promise.all([
                    getStudent(id),
                    getAnnotationManifest(id),
                ]);
                setStudent(studentData);
                setManifest(manifestData);
            } catch (err) {
                setError(err.response?.data?.detail || err.message || 'Failed to load data');
            } finally {
                setLoading(false);
            }
        }
        load();
    }, [id]);

    const showToast = useCallback((msg) => {
        setToast(msg);
        setTimeout(() => setToast(''), 3200);
    }, []);

    /* ── Change handlers ────────────────────────────────────────────────── */

    const handleChangeMarks = useCallback((mkey, field, val) => {
        setChanges(prev => ({
            ...prev,
            [mkey]: { ...(prev[mkey] || {}), [field]: val },
        }));
    }, []);

    const handleChangeFeedback = useCallback((mkey, text) => {
        setChanges(prev => ({
            ...prev,
            [mkey]: { ...(prev[mkey] || {}), feedback_text: text },
        }));
    }, []);

    const handleRemoveStamp = useCallback((mkey, isRemoved) => {
        setChanges(prev => ({
            ...prev,
            [mkey]: { ...(prev[mkey] || {}), remove_stamp: isRemoved },
        }));
    }, []);

    const handleChangeTickCross = useCallback((mkey, idx, action) => {
        setChanges(prev => {
            const q        = prev[mkey] || {};
            const tcs      = [...(q.ticks_crosses || [])];
            const existing = tcs.findIndex(c => c.index === idx);
            if (existing >= 0) tcs[existing] = { index: idx, action };
            else               tcs.push({ index: idx, action });
            return { ...prev, [mkey]: { ...q, ticks_crosses: tcs } };
        });
    }, []);

    const handleDeleteTickCross = useCallback((mkey, idx, markForDelete) => {
        setChanges(prev => {
            const q           = prev[mkey] || {};
            const deletions   = new Set(q.delete_tick_indices || []);
            if (markForDelete) deletions.add(idx);
            else               deletions.delete(idx);
            const newDeletions = [...deletions];
            const newQ = { ...q };
            if (newDeletions.length === 0) delete newQ.delete_tick_indices;
            else newQ.delete_tick_indices = newDeletions;
            return { ...prev, [mkey]: newQ };
        });
    }, []);

    // dir is 'up', 'down', 'left', 'right'
    const handleMoveStamp = useCallback((mkey, dir) => {
        setChanges(prev => {
            const q = prev[mkey] || {};
            const moveData = { ...(q.move_stamp || { up: 0, down: 0, left: 0, right: 0 }) };
            moveData[dir] += 1;
            return { ...prev, [mkey]: { ...q, move_stamp: moveData } };
        });
    }, []);

    const handleMoveFeedback = useCallback((mkey, dir) => {
        setChanges(prev => {
            const q = prev[mkey] || {};
            const moveData = { ...(q.move_feedback || { up: 0, down: 0, left: 0, right: 0 }) };
            moveData[dir] += 1;
            return { ...prev, [mkey]: { ...q, move_feedback: moveData } };
        });
    }, []);

    const handleMoveTick = useCallback((mkey, idx, dir) => {
        setChanges(prev => {
            const q = prev[mkey] || {};
            const moveIndices = { ...(q.move_tick_indices || {}) };
            const moveData = { ...(moveIndices[idx] || { up: 0, down: 0, left: 0, right: 0 }) };
            moveData[dir] += 1;
            moveIndices[idx] = moveData;
            return { ...prev, [mkey]: { ...q, move_tick_indices: moveIndices } };
        });
    }, []);

    const resetAll = () => {
        setChanges({});
        showToast('All changes reset');
    };

    /* ── Submit Helper ──────────────────────────────────────────────────── */

    // Convert aggregate state to API payload (list of direction multipliers)
    const condenseMoves = (moveState) => {
        if (!moveState) return null;
        const res = [];
        for (const dir of ['up', 'down', 'left', 'right']) {
            if (moveState[dir] > 0) res.push({ direction: dir, multiplier: moveState[dir] });
        }
        return res.length > 0 ? res : null;
    };

    const handleSubmit = async () => {
        if (Object.keys(changes).length === 0) {
            showToast('No changes to apply');
            return;
        }

        setSubmitting(true);
        try {
            const corrections = {};
            for (const [mkey, corr] of Object.entries(changes)) {
                const c = {};
                if (corr.marks_obtained    !== undefined) c.marks_obtained    = corr.marks_obtained;
                if (corr.marks_total       !== undefined) c.marks_total       = corr.marks_total;
                if (corr.feedback_text     !== undefined) c.feedback_text     = corr.feedback_text;
                if (corr.ticks_crosses?.length > 0)      c.ticks_crosses     = corr.ticks_crosses;
                if (corr.delete_tick_indices?.length > 0) c.delete_tick_indices = corr.delete_tick_indices;
                if (corr.remove_stamp) c.remove_stamp = true;
                
                const ms = condenseMoves(corr.move_stamp);
                if (ms) c.move_stamp = ms;
                
                const mf = condenseMoves(corr.move_feedback);
                if (mf) c.move_feedback = mf;
                
                if (corr.move_tick_indices) {
                    const mtList = [];
                    for (const [idxStr, moveState] of Object.entries(corr.move_tick_indices)) {
                        const moves = condenseMoves(moveState);
                        if (moves) {
                            moves.forEach(m => mtList.push({ index: parseInt(idxStr), direction: m.direction, multiplier: m.multiplier }));
                        }
                    }
                    if (mtList.length > 0) c.move_tick_indices = mtList;
                }

                if (Object.keys(c).length > 0) corrections[mkey] = c;
            }

            const blob = await patchCheckedCopy(id, corrections);
            saveBlob(blob, `${student?.student_name || 'student'}_checked_copy_edited.pdf`);
            showToast('✓ Edited copy downloaded successfully!');
        } catch (err) {
            const detail = err.response?.data?.detail || err.message || 'Failed to generate patched copy';
            setError(detail);
        } finally {
            setSubmitting(false);
        }
    };

    /* ── Derived state ──────────────────────────────────────────────────── */

    const dirtyCount   = Object.keys(changes).length;
    const questions    = manifest?.questions || {};
    const qKeys        = Object.keys(questions).sort();

    const gtOriginal   = manifest?.grand_total || { obtained: 0, total: 0 };
    let   newObtained  = gtOriginal.obtained;
    for (const [mkey, corr] of Object.entries(changes)) {
        if (corr.marks_obtained !== undefined && questions[mkey]) {
            newObtained += corr.marks_obtained - questions[mkey].marks_obtained;
        }
    }

    /* ── Render ─────────────────────────────────────────────────────────── */

    if (loading) {
        return (
            <div className="ecc-loading">
                <div className="ecc-spinner" />
                <p>Loading annotation data…</p>
            </div>
        );
    }

    if (error) {
        return (
            <div className="ecc-page">
                <div className="ecc-error-panel">
                    <div className="ecc-error-icon">⚠️</div>
                    <h2>Cannot load editor</h2>
                    <p>{typeof error === 'object' ? JSON.stringify(error) : error}</p>
                    <button className="ecc-back-btn" onClick={() => navigate(`/checked-paper/${id}`)}>
                        ← Back
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="ecc-page">
            <header className="ecc-header">
                <button id="ecc-back-btn" className="ecc-back-btn" onClick={() => navigate(`/checked-paper/${id}`)}>
                    ← Back
                </button>
                <div className="ecc-header-center">
                    <h1 className="ecc-title">Advanced Post-Grading Editor</h1>
                    {student && (
                        <p className="ecc-subtitle">
                            {student.student_name}
                            {student.roll_number ? ` · Roll ${student.roll_number}` : ''}
                        </p>
                    )}
                </div>
                <div className="ecc-header-actions">
                    {dirtyCount > 0 && (
                        <button id="ecc-reset-btn" className="ecc-reset-btn" onClick={resetAll}>
                            Reset all
                        </button>
                    )}
                    <button
                        id="ecc-submit-btn"
                        className={`ecc-submit-btn ${submitting ? 'loading' : ''}`}
                        onClick={handleSubmit}
                        disabled={submitting || dirtyCount === 0}
                    >
                        {submitting ? (
                            <><span className="btn-spinner" /> Generating…</>
                        ) : (
                            `⬇ Save & Download Edited Copy${dirtyCount > 0 ? ` (${dirtyCount} change${dirtyCount > 1 ? 's' : ''})` : ''}`
                        )}
                    </button>
                </div>
            </header>

            <div className="ecc-grand-banner">
                <div className="ecc-grand-label">Grand Total Preview</div>
                <div className="ecc-grand-score">
                    <span className={`ecc-grand-num ${newObtained !== gtOriginal.obtained ? 'changed' : ''}`}>
                        {fmtNum(newObtained)}
                    </span>
                    <span className="ecc-grand-sep">/</span>
                    <span className="ecc-grand-num">{fmtNum(gtOriginal.total)}</span>
                </div>
                {newObtained !== gtOriginal.obtained && (
                    <div className="ecc-grand-diff">
                        was {fmtNum(gtOriginal.obtained)} · Δ {newObtained > gtOriginal.obtained ? '+' : ''}{fmtNum(newObtained - gtOriginal.obtained)}
                    </div>
                )}
            </div>

            <main className="ecc-main">
                {qKeys.length === 0 ? (
                    <div className="ecc-empty">
                        <p>No questions found in the annotation manifest.</p>
                    </div>
                ) : (
                    <div className="ecc-questions">
                        {qKeys.map(mkey => (
                            <QuestionCard
                                key={mkey}
                                mkey={mkey}
                                question={questions[mkey]}
                                changes={changes}
                                onChangeMarks={handleChangeMarks}
                                onChangeFeedback={handleChangeFeedback}
                                onRemoveStamp={handleRemoveStamp}
                                onChangeTickCross={handleChangeTickCross}
                                onDeleteTickCross={handleDeleteTickCross}
                                onMoveStamp={handleMoveStamp}
                                onMoveFeedback={handleMoveFeedback}
                                onMoveTick={handleMoveTick}
                            />
                        ))}
                    </div>
                )}
            </main>

            {dirtyCount > 0 && (
                <div className="ecc-sticky-bar">
                    <span className="ecc-sticky-label">
                        {dirtyCount} question{dirtyCount > 1 ? 's' : ''} edited
                    </span>
                    <button
                        id="ecc-sticky-submit"
                        className={`ecc-submit-btn ${submitting ? 'loading' : ''}`}
                        onClick={handleSubmit}
                        disabled={submitting}
                    >
                        {submitting ? <><span className="btn-spinner" /> Generating…</> : '⬇ Save & Download'}
                    </button>
                </div>
            )}

            {toast && (
                <div className="ecc-toast">
                    {toast}
                </div>
            )}
        </div>
    );
}

export default EditCheckedCopy;
