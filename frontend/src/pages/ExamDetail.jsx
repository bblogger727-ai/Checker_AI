import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getExam, getStudents, uploadStudentPaper, downloadResultPdf } from '../services/api';
import './ExamDetail.css';

function ExamDetail() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [exam, setExam] = useState(null);
    const [students, setStudents] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showUpload, setShowUpload] = useState(false);
    const [uploading, setUploading] = useState(false);

    // Upload form state
    const [uploadForm, setUploadForm] = useState({
        studentName: '',
        rollNumber: '',
        answerPdf: null,
    });

    useEffect(() => {
        loadData();
    }, [id]);

    const loadData = async () => {
        try {
            const [examData, studentsData] = await Promise.all([
                getExam(id),
                getStudents(id),
            ]);
            setExam(examData);
            setStudents(studentsData);
        } catch (err) {
            console.error('Failed to load exam:', err);
        } finally {
            setLoading(false);
        }
    };

    const handleUpload = async (e) => {
        e.preventDefault();
        if (!uploadForm.answerPdf) {
            alert('Please select an answer PDF');
            return;
        }

        setUploading(true);
        try {
            const student = await uploadStudentPaper(
                id,
                uploadForm.studentName,
                uploadForm.rollNumber,
                uploadForm.answerPdf
            );
            setShowUpload(false);
            setUploadForm({ studentName: '', rollNumber: '', answerPdf: null });
            navigate(`/checked-paper/${student.id}`);
        } catch (err) {
            alert('Failed to upload: ' + (err.response?.data?.detail || err.message));
        } finally {
            setUploading(false);
        }
    };

    const handleDownloadPdf = async (studentId, studentName) => {
        try {
            const blob = await downloadResultPdf(studentId);
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${studentName}_result.pdf`;
            a.click();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            alert('Failed to download PDF');
        }
    };

    const getStatusColor = (status) => {
        switch (status) {
            case 'completed': return 'status-ready';
            case 'processing': return 'status-processing';
            case 'pending': return 'status-pending';
            default: return 'status-failed';
        }
    };

    const getGradeColor = (grade) => {
        if (!grade) return '';
        if (grade.startsWith('A')) return 'grade-a';
        if (grade.startsWith('B')) return 'grade-b';
        if (grade.startsWith('C')) return 'grade-c';
        if (grade === 'D') return 'grade-d';
        return 'grade-f';
    };

    if (loading) {
        return <div className="loading-screen"><div className="spinner"></div></div>;
    }

    if (!exam) {
        return <div className="error">Exam not found</div>;
    }

    return (
        <div className="exam-detail">
            <header className="header">
                <button onClick={() => navigate('/')} className="back-btn">
                    ← Back
                </button>
                <h1>{exam.name}</h1>
                <span className={`status-badge ${exam.processing_status === 'ready' ? 'status-ready' : 'status-processing'}`}>
                    {exam.processing_status}
                </span>
            </header>

            <main className="main-content">
                <div className="exam-info">
                    {exam.subject && <p><strong>Subject:</strong> {exam.subject}</p>}
                    {exam.exam_date && (
                        <p><strong>Date:</strong> {new Date(exam.exam_date).toLocaleDateString()}</p>
                    )}
                </div>

                <div className="students-section">
                    <div className="section-header">
                        <h2>Student Papers ({students.length})</h2>
                        <button
                            onClick={() => setShowUpload(true)}
                            className="upload-btn"
                            disabled={exam.processing_status !== 'ready'}
                        >
                            + Upload Paper
                        </button>
                    </div>

                    {exam.processing_status !== 'ready' && (
                        <div className="warning-message">
                            ⏳ Please wait for solution processing to complete before uploading student papers.
                        </div>
                    )}

                    {students.length === 0 ? (
                        <div className="empty-state">
                            <div className="empty-icon">📄</div>
                            <h3>No student papers yet</h3>
                            <p>Upload student answer sheets to start grading</p>
                        </div>
                    ) : (
                        <div className="students-table-wrapper">
                            <table className="students-table">
                                <thead>
                                    <tr>
                                        <th>Student Name</th>
                                        <th>Roll No.</th>
                                        <th>Status</th>
                                        <th>Marks</th>
                                        <th>Percentage</th>
                                        <th>Grade</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {students.map((student) => (
                                        <tr key={student.id}>
                                            <td className="student-name">{student.student_name}</td>
                                            <td>{student.roll_number || '-'}</td>
                                            <td>
                                                <span className={`status-badge ${getStatusColor(student.status)}`}>
                                                    {student.status}
                                                </span>
                                            </td>
                                            <td>
                                                {student.status === 'completed'
                                                    ? `${student.obtained_marks}/${student.total_marks}`
                                                    : '-'
                                                }
                                            </td>
                                            <td>
                                                {student.percentage != null ? `${student.percentage}%` : '-'}
                                            </td>
                                            <td>
                                                <span className={`grade-badge ${getGradeColor(student.grade)}`}>
                                                    {student.grade || '-'}
                                                </span>
                                            </td>
                                            <td>
                                                {student.status === 'completed' && (
                                                    <div className="student-actions">
                                                        <button
                                                            className="download-btn"
                                                            onClick={() => navigate(`/checked-paper/${student.id}`)}
                                                        >
                                                            View Downloads
                                                        </button>
                                                        <button
                                                            className="report-btn"
                                                            onClick={() => handleDownloadPdf(student.id, student.student_name)}
                                                        >
                                                            Result PDF
                                                        </button>
                                                    </div>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </main>

            {showUpload && (
                <div className="modal-overlay" onClick={() => setShowUpload(false)}>
                    <div className="modal" onClick={(e) => e.stopPropagation()}>
                        <h2>Upload Student Paper</h2>
                        <form onSubmit={handleUpload}>
                            <div className="form-group">
                                <label>Student Name *</label>
                                <input
                                    type="text"
                                    value={uploadForm.studentName}
                                    onChange={(e) => setUploadForm({ ...uploadForm, studentName: e.target.value })}
                                    placeholder="Enter student's name"
                                    required
                                />
                            </div>
                            <div className="form-group">
                                <label>Roll Number</label>
                                <input
                                    type="text"
                                    value={uploadForm.rollNumber}
                                    onChange={(e) => setUploadForm({ ...uploadForm, rollNumber: e.target.value })}
                                    placeholder="Optional"
                                />
                            </div>
                            <div className="form-group">
                                <label>Answer Sheet PDF *</label>
                                <input
                                    type="file"
                                    accept=".pdf"
                                    onChange={(e) => setUploadForm({ ...uploadForm, answerPdf: e.target.files[0] })}
                                    required
                                />
                            </div>
                            <div className="modal-actions">
                                <button type="button" onClick={() => setShowUpload(false)} className="cancel-btn">
                                    Cancel
                                </button>
                                <button type="submit" className="submit-btn" disabled={uploading}>
                                    {uploading ? 'Uploading & Grading...' : 'Upload & Grade'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}

export default ExamDetail;
