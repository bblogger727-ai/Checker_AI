import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../App';
import { getExams, createExam, deleteExam } from '../services/api';
import './Dashboard.css';

function Dashboard() {
    const { user, logout } = useAuth();
    const navigate = useNavigate();
    const [exams, setExams] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showCreate, setShowCreate] = useState(false);
    const [creating, setCreating] = useState(false);

    // Create form state
    const [newExam, setNewExam] = useState({
        name: '',
        subject: '',
        examDate: '',
        solutionPdf: null,
    });

    useEffect(() => {
        loadExams();
    }, []);

    const loadExams = async () => {
        try {
            const data = await getExams();
            setExams(data);
        } catch (err) {
            console.error('Failed to load exams:', err);
        } finally {
            setLoading(false);
        }
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        if (!newExam.solutionPdf) {
            alert('Please select a solution PDF');
            return;
        }

        setCreating(true);
        try {
            await createExam(
                newExam.name,
                newExam.subject,
                newExam.examDate,
                newExam.solutionPdf
            );
            setShowCreate(false);
            setNewExam({ name: '', subject: '', examDate: '', solutionPdf: null });
            loadExams();
        } catch (err) {
            alert('Failed to create exam: ' + (err.response?.data?.detail || err.message));
        } finally {
            setCreating(false);
        }
    };

    const handleDelete = async (id) => {
        if (!confirm('Are you sure you want to delete this exam?')) return;

        try {
            await deleteExam(id);
            loadExams();
        } catch (err) {
            alert('Failed to delete exam');
        }
    };

    const getStatusColor = (status) => {
        switch (status) {
            case 'ready': return 'status-ready';
            case 'processing': return 'status-processing';
            case 'pending': return 'status-pending';
            default: return 'status-failed';
        }
    };

    return (
        <div className="dashboard">
            <header className="header">
                <div className="header-left">
                    <span className="logo-icon">🎓</span>
                    <h1>Student Evaluator</h1>
                    <span className="module-indicator checker-indicator">✓ CheckerAI</span>
                </div>
                <div className="header-right">
                    <button onClick={() => navigate('/setter')} className="setter-btn">
                        📝 SetterAI
                    </button>
                    <button onClick={() => navigate('/mentor')} className="mentor-btn">
                        👨‍🏫 MentorAI
                    </button>
                    <span className="user-name">{user?.name || user?.email}</span>
                    <button onClick={logout} className="logout-btn">Logout</button>
                </div>
            </header>

            <main className="main-content">
                <div className="content-header">
                    <h2>Your Exams</h2>
                    <button onClick={() => setShowCreate(true)} className="create-btn">
                        + New Exam
                    </button>
                </div>

                {loading ? (
                    <div className="loading">Loading exams...</div>
                ) : exams.length === 0 ? (
                    <div className="empty-state">
                        <div className="empty-icon">📋</div>
                        <h3>No exams yet</h3>
                        <p>Create your first exam to start evaluating student papers</p>
                        <button onClick={() => setShowCreate(true)} className="create-btn">
                            Create Exam
                        </button>
                    </div>
                ) : (
                    <div className="exams-grid">
                        {exams.map((exam) => (
                            <div
                                key={exam.id}
                                className="exam-card"
                                onClick={() => navigate(`/exam/${exam.id}`)}
                            >
                                <div className="exam-header">
                                    <h3>{exam.name}</h3>
                                    <span className={`status-badge ${getStatusColor(exam.processing_status)}`}>
                                        {exam.processing_status}
                                    </span>
                                </div>
                                <div className="exam-details">
                                    {exam.subject && <p className="subject">{exam.subject}</p>}
                                    {exam.exam_date && (
                                        <p className="date">
                                            {new Date(exam.exam_date).toLocaleDateString()}
                                        </p>
                                    )}
                                </div>
                                <div className="exam-footer">
                                    <span className="student-count">
                                        {exam.student_count} student{exam.student_count !== 1 ? 's' : ''}
                                    </span>
                                    <button
                                        className="delete-btn"
                                        onClick={(e) => { e.stopPropagation(); handleDelete(exam.id); }}
                                    >
                                        🗑️
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </main>

            {showCreate && (
                <div className="modal-overlay" onClick={() => setShowCreate(false)}>
                    <div className="modal" onClick={(e) => e.stopPropagation()}>
                        <h2>Create New Exam</h2>
                        <form onSubmit={handleCreate}>
                            <div className="form-group">
                                <label>Exam Name *</label>
                                <input
                                    type="text"
                                    value={newExam.name}
                                    onChange={(e) => setNewExam({ ...newExam, name: e.target.value })}
                                    placeholder="e.g., CA Final - Direct Tax"
                                    required
                                />
                            </div>
                            <div className="form-group">
                                <label>Subject</label>
                                <input
                                    type="text"
                                    value={newExam.subject}
                                    onChange={(e) => setNewExam({ ...newExam, subject: e.target.value })}
                                    placeholder="e.g., Taxation"
                                />
                            </div>
                            <div className="form-group">
                                <label>Exam Date</label>
                                <input
                                    type="date"
                                    value={newExam.examDate}
                                    onChange={(e) => setNewExam({ ...newExam, examDate: e.target.value })}
                                />
                            </div>
                            <div className="form-group">
                                <label>Solution PDF *</label>
                                <input
                                    type="file"
                                    accept=".pdf"
                                    onChange={(e) => setNewExam({ ...newExam, solutionPdf: e.target.files[0] })}
                                    required
                                />
                                <p className="help-text">
                                    Upload the solution PDF. We'll automatically extract questions and model answers.
                                </p>
                            </div>
                            <div className="modal-actions">
                                <button type="button" onClick={() => setShowCreate(false)} className="cancel-btn">
                                    Cancel
                                </button>
                                <button type="submit" className="submit-btn" disabled={creating}>
                                    {creating ? 'Creating...' : 'Create Exam'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}

export default Dashboard;
