import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { downloadCheckedCopyPdf, downloadResultPdf, getStudent } from '../services/api';
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
                        <strong>{student.percentage != null ? `${student.percentage}%` : '-'}</strong>
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
                            disabled={!isCompleted || downloading === 'checked-copy'}
                            className="primary-action"
                        >
                            {downloading === 'checked-copy' ? 'Preparing...' : 'Download Checked Copy'}
                        </button>
                        <button
                            onClick={handleDownloadReport}
                            disabled={!isCompleted || downloading === 'report'}
                            className="secondary-action"
                        >
                            {downloading === 'report' ? 'Preparing...' : 'Download Result Report'}
                        </button>
                        <button
                            id="edit-corrections-btn"
                            onClick={() => navigate(`/checked-paper/${student.id}/edit`)}
                            disabled={!isCompleted}
                            className="edit-corrections-btn"
                        >
                            ✏️ Edit Corrections
                        </button>
                    </div>
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
