import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getPaper, updatePaper, finalizePaper, generateSolution, publishPaper } from '../services/setterApi';
import './PaperEditor.css';

function PaperEditor() {
    const { id } = useParams();
    const navigate = useNavigate();

    const [paper, setPaper] = useState(null);
    const [editedPaper, setEditedPaper] = useState(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [processing, setProcessing] = useState(false);

    useEffect(() => {
        loadPaper();
    }, [id]);

    const loadPaper = async () => {
        try {
            const data = await getPaper(id);
            setPaper(data);
            setEditedPaper(data.edited_paper_json || data.generated_paper_json || {});
        } catch (err) {
            alert('Failed to load paper');
            navigate('/setter');
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        setSaving(true);
        try {
            await updatePaper(id, editedPaper);
            alert('Saved!');
            loadPaper();
        } catch (err) {
            alert('Failed to save: ' + (err.response?.data?.detail || err.message));
        } finally {
            setSaving(false);
        }
    };

    const handleFinalize = async () => {
        if (!confirm('Finalize this paper? No more edits will be allowed.')) return;
        setProcessing(true);
        try {
            await finalizePaper(id);
            loadPaper();
        } catch (err) {
            alert('Failed to finalize');
        } finally {
            setProcessing(false);
        }
    };

    const handleGenerateSolution = async () => {
        if (!confirm('Generate solution for this paper?')) return;
        setProcessing(true);
        try {
            await generateSolution(id);
            loadPaper();
            alert('Solution generated!');
        } catch (err) {
            alert('Failed to generate solution: ' + (err.response?.data?.detail || err.message));
        } finally {
            setProcessing(false);
        }
    };

    const handlePublish = async () => {
        if (!confirm('Publish this paper to CheckerAI for grading?')) return;
        setProcessing(true);
        try {
            await publishPaper(id);
            loadPaper();
            alert('Paper published to CheckerAI!');
        } catch (err) {
            alert('Failed to publish: ' + (err.response?.data?.detail || err.message));
        } finally {
            setProcessing(false);
        }
    };

    const updateQuestion = (sectionIndex, questionIndex, field, value) => {
        const updated = { ...editedPaper };
        updated.sections[sectionIndex].questions[questionIndex][field] = value;
        setEditedPaper(updated);
    };

    const addQuestion = (sectionIndex) => {
        const updated = { ...editedPaper };
        const section = updated.sections[sectionIndex];
        const newNum = section.questions.length + 1;
        section.questions.push({
            question_number: newNum,
            question_text: '',
            marks: 4,
            topic: '',
            difficulty: 'Medium'
        });
        setEditedPaper(updated);
    };

    const removeQuestion = (sectionIndex, questionIndex) => {
        const updated = { ...editedPaper };
        updated.sections[sectionIndex].questions.splice(questionIndex, 1);
        // Renumber
        updated.sections[sectionIndex].questions.forEach((q, i) => {
            q.question_number = i + 1;
        });
        setEditedPaper(updated);
    };

    if (loading) {
        return <div className="editor-loading">Loading paper...</div>;
    }

    const isReadOnly = paper.status === 'published';
    const canFinalize = paper.status === 'draft' || paper.status === 'reviewing';
    const canGenSolution = paper.status === 'finalized' && !paper.solution_json;
    const canPublish = paper.status === 'finalized' && paper.solution_json;

    return (
        <div className="paper-editor">
            <header className="editor-header">
                <button onClick={() => navigate('/setter')} className="back-btn">← Back</button>
                <div className="editor-title">
                    <h1>{editedPaper.title || 'Paper Editor'}</h1>
                    <span className={`status-badge status-${paper.status}`}>{paper.status}</span>
                </div>
                <div className="editor-actions">
                    {!isReadOnly && (
                        <button onClick={handleSave} disabled={saving} className="save-btn">
                            {saving ? 'Saving...' : '💾 Save Draft'}
                        </button>
                    )}
                    {canFinalize && (
                        <button onClick={handleFinalize} disabled={processing} className="finalize-btn">
                            ✓ Finalize
                        </button>
                    )}
                    {canGenSolution && (
                        <button onClick={handleGenerateSolution} disabled={processing} className="solution-btn">
                            📝 Generate Solution
                        </button>
                    )}
                    {canPublish && (
                        <button onClick={handlePublish} disabled={processing} className="publish-btn">
                            🚀 Publish to Checker
                        </button>
                    )}
                </div>
            </header>

            <main className="editor-content">
                {/* Paper Metadata */}
                <div className="paper-meta">
                    <div className="meta-row">
                        <span><strong>Subject:</strong> {editedPaper.subject}</span>
                        <span><strong>Total Marks:</strong> {editedPaper.total_marks}</span>
                        <span><strong>Duration:</strong> {editedPaper.duration_minutes} mins</span>
                    </div>
                </div>

                {/* Instructions */}
                <div className="instructions-section">
                    <h3>Instructions</h3>
                    <ul>
                        {(editedPaper.instructions || []).map((inst, i) => (
                            <li key={i}>{inst}</li>
                        ))}
                    </ul>
                </div>

                {/* Sections */}
                {(editedPaper.sections || []).map((section, sectionIndex) => (
                    <div key={sectionIndex} className="paper-section">
                        <div className="section-header">
                            <h2>{section.section_name}</h2>
                            <span className="section-marks">({section.section_marks} marks)</span>
                        </div>
                        <p className="section-instructions">{section.instructions}</p>

                        <div className="questions-list">
                            {(section.questions || []).map((question, qIndex) => (
                                <div key={qIndex} className="question-card">
                                    <div className="question-header">
                                        <span className="q-number">Q{question.question_number}</span>
                                        <span className="q-marks">[{question.marks} marks]</span>
                                        {question.topic && <span className="q-topic">{question.topic}</span>}
                                        {!isReadOnly && (
                                            <button
                                                className="remove-q-btn"
                                                onClick={() => removeQuestion(sectionIndex, qIndex)}
                                            >
                                                ✕
                                            </button>
                                        )}
                                    </div>

                                    {isReadOnly ? (
                                        <p className="question-text">{question.question_text}</p>
                                    ) : (
                                        <textarea
                                            className="question-input"
                                            value={question.question_text}
                                            onChange={(e) => updateQuestion(sectionIndex, qIndex, 'question_text', e.target.value)}
                                            rows={4}
                                            placeholder="Enter question text..."
                                        />
                                    )}

                                    {/* MCQ Options */}
                                    {question.options && (
                                        <div className="mcq-options">
                                            {Object.entries(question.options).filter(([k]) => k !== 'correct').map(([key, value]) => (
                                                <div key={key} className={`option ${question.options.correct === key ? 'correct' : ''}`}>
                                                    <span className="option-key">({key})</span> {value}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            ))}

                            {!isReadOnly && (
                                <button
                                    className="add-question-btn"
                                    onClick={() => addQuestion(sectionIndex)}
                                >
                                    + Add Question
                                </button>
                            )}
                        </div>
                    </div>
                ))}

                {/* Solution Preview */}
                {paper.solution_json && (
                    <div className="solution-preview">
                        <h2>📝 Solution Generated</h2>
                        <p>Solution has been generated with {paper.solution_json.sections?.length || 0} sections.</p>
                        <details>
                            <summary>View Solution JSON</summary>
                            <pre>{JSON.stringify(paper.solution_json, null, 2)}</pre>
                        </details>
                    </div>
                )}
            </main>
        </div>
    );
}

export default PaperEditor;
