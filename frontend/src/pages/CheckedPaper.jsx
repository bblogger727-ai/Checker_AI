import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { downloadCheckedCopyPdf, downloadResultPdf, downloadPipelineResult, getStudent, recheckPipeline, getPipelineStatus } from '../services/api';
import './CheckedPaper.css';

function saveBlob(blob, filename) {
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    window.URL.revokeObjectURL(url);
}

function CheckedPaper() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [student, setStudent] = useState(null);
    const [loading, setLoading] = useState(true);
    const [downloading, setDownloading] = useState(null);
    const [error, setError] = useState('');
    const [recheckStatus, setRecheckStatus] = useState(null); // null | 'running' | 'done' | 'failed'
    const [recheckMsg, setRecheckMsg] = useState('');
    const pollRef = useRef(null);

    useEffect(() => {
        async function loadStudent() {
            try {
                const data = await getStudent(id);
                setStudent(data);
            } catch (err) {
                setError(err.response?.data?.detail || err.message);
            } finally {
                setLoading(false);
            }
        }

        loadStudent();
        return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }, [id]);

    const handleDownloadReport = async () => {
        if (!student) return;
        setDownloading('report');
        try {
            const blob = await downloadResultPdf(student.id);
            saveBlob(blob, `${student.student_name}_result.pdf`);
        } catch (err) {
            alert('Failed to download result report: ' + (err.response?.data?.detail || err.message));
        } finally {
            setDownloading(null);
        }
    };

    const handleDownloadStudentReport = async () => {
        if (!student) return;
        setDownloading('student_report');
        try {
            const blob = await downloadPipelineResult(student.id, 'student_report');
            saveBlob(blob, `${student.student_name}_student_report.txt`);
        } catch (err) {
            alert('Failed to download student report: ' + (err.response?.data?.detail || err.message));
        } finally {
            setDownloading(null);
        }
    };

    const handleDownloadCheckedCopy = async () => {
        if (!student) return;
        setDownloading('checked-copy');
        try {
            const blob = await downloadCheckedCopyPdf(student.id);
            saveBlob(blob, `${student.student_name}_checked_copy.pdf`);
        } catch (err) {
            alert('Failed to download checked copy: ' + (err.response?.data?.detail || err.message));
        } finally {
            setDownloading(null);
        }
    };

    const handleRecheck = async () => {
        if (!student) return;
        setRecheckStatus('running');
        setRecheckMsg('Submitting recheck…');

        try {
            await recheckPipeline(student.id);
        } catch (err) {
            setRecheckStatus('failed');
            setRecheckMsg(err.response?.data?.detail || err.message);
            return;
        }

        // Poll every 3 s until done or failed
        setRecheckMsg('Re-generating checked copy…');
        pollRef.current = setInterval(async () => {
            try {
                const status = await getPipelineStatus(student.id);
                if (status.status === 'done') {
                    clearInterval(pollRef.current);
                    setRecheckStatus('done');
                    setRecheckMsg('Recheck complete! Downloading…');
                    try {
                        const blob = await downloadPipelineResult(student.id, 'checked_copy');
                        saveBlob(blob, `${student.student_name}_checked_copy.pdf`);
                    } catch (_) { /* user can still download manually */ }
                } else if (status.status === 'failed') {
                    clearInterval(pollRef.current);
                    setRecheckStatus('failed');
                    setRecheckMsg(status.message || 'Recheck failed');
                } else {
                    setRecheckMsg(status.message || 'Re-generating checked copy…');
                }
            } catch (_) { /* ignore transient poll errors */ }
        }, 3000);
    };

    if (loading) {
        return <div className="checked-paper-loading">Preparing downloads...</div>;
    }

    if (error || !student) {
        return (
            <div className="checked-paper-page">
                <div className="checked-paper-panel">
                    <h1>Result unavailable</h1>
                    <p>{typeof error === 'object' ? JSON.stringify(error) : (error || 'Student paper not found')}</p>
                    <button onClick={() => navigate('/')} className="secondary-action">Back to Dashboard</button>
                </div>
            </div>
        );
    }

    const isCompleted = student.status === 'completed';
    const isRechecking = recheckStatus === 'running';

    return (
        <div className="checked-paper-page">
            <header className="checked-paper-header">
                <button onClick={() => navigate(`/exam/${student.exam_id}`)} className="back-btn">
                    Back
                </button>
                <div>
                    <h1>Checked Paper</h1>
                    <p>{student.student_name}</p>
                </div>
            </header>

            <main className="checked-paper-content">
                <section className="result-summary">
                    <div>
                        <span className="summary-label">Status</span>
                        <strong>{student.status}</strong>
                    </div>
                    <div>
                        <span className="summary-label">Marks</span>
                        <strong>
                            {isCompleted ? `${student.obtained_marks}/${student.total_marks}` : '-'}
                        </strong>
                    </div>
                    <div>
                        <span className="summary-label">Percentage</span>
                        <strong>{student.percentage != null ? `${+Number(student.percentage).toFixed(2)}%` : '-'}</strong>
                    </div>
                    <div>
                        <span className="summary-label">Grade</span>
                        <strong>{student.grade || '-'}</strong>
                    </div>
                </section>

                <section className="download-panel">
                    <h2>Downloads</h2>
                    <div className="download-actions">
                        <button
                            onClick={handleDownloadCheckedCopy}
                            disabled={!isCompleted || downloading === 'checked-copy' || isRechecking}
                            className="primary-action"
                        >
                            {downloading === 'checked-copy' ? 'Preparing...' : 'Download Checked Copy'}
                        </button>
                        <button
                            onClick={handleDownloadReport}
                            disabled={!isCompleted || downloading === 'report' || isRechecking}
                            className="secondary-action"
                        >
                            {downloading === 'report' ? 'Preparing...' : 'Download Result Report'}
                        </button>
                        <button
                            onClick={handleDownloadStudentReport}
                            disabled={!isCompleted || downloading === 'student_report' || isRechecking}
                            className="secondary-action"
                        >
                            {downloading === 'student_report' ? 'Preparing...' : 'Download Student Report'}
                        </button>
                        <button
                            id="edit-corrections-btn"
                            onClick={() => navigate(`/checked-paper/${student.id}/edit`)}
                            disabled={!isCompleted || isRechecking}
                            className="edit-corrections-btn"
                        >
                            ✏️ Edit Corrections
                        </button>
                        <button
                            id="recheck-copy-btn"
                            onClick={handleRecheck}
                            disabled={!isCompleted || isRechecking}
                            className="recheck-btn"
                        >
                            {isRechecking ? '⏳ Rechecking…' : '🔄 Recheck Copy'}
                        </button>
                    </div>

                    {recheckStatus && (
                        <div className={`recheck-status recheck-status--${recheckStatus}`}>
                            {recheckMsg}
                        </div>
                    )}

                    {!isCompleted && (
                        <p className="download-note">
                            The checked copy will be available once grading is complete.
                        </p>
                    )}
                </section>
            </main>
        </div>
    );
}

export default CheckedPaper;
