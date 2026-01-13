import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
    getStudent,
    updateStudent,
    getProblems,
    createConsultation,
    generateReport,
    sendReport
} from '../services/mentorApi';
import './StudentProfile.css';

function StudentProfile() {
    const { id } = useParams();
    const navigate = useNavigate();

    const [student, setStudent] = useState(null);
    const [loading, setLoading] = useState(true);
    const [editing, setEditing] = useState(false);
    const [editForm, setEditForm] = useState({ phone: '', email: '' });

    // Consultation modal
    const [showConsultation, setShowConsultation] = useState(false);
    const [problems, setProblems] = useState([]);
    const [selectedProblems, setSelectedProblems] = useState([]);
    const [customProblem, setCustomProblem] = useState('');
    const [mentorNotes, setMentorNotes] = useState('');
    const [processing, setProcessing] = useState(false);
    const [consultationId, setConsultationId] = useState(null);
    const [reportGenerated, setReportGenerated] = useState(false);
    const [whatsappLink, setWhatsappLink] = useState(null);

    useEffect(() => {
        loadStudent();
        loadProblems();
    }, [id]);

    const loadStudent = async () => {
        try {
            const data = await getStudent(id);
            setStudent(data);
            setEditForm({ phone: data.phone || '', email: data.email || '' });
        } catch (err) {
            alert('Failed to load student');
            navigate('/mentor');
        } finally {
            setLoading(false);
        }
    };

    const loadProblems = async () => {
        try {
            const data = await getProblems();
            setProblems(data);
        } catch (err) {
            console.error('Failed to load problems:', err);
        }
    };

    const handleSaveContact = async () => {
        try {
            await updateStudent(id, editForm);
            await loadStudent();
            setEditing(false);
        } catch (err) {
            alert('Failed to update');
        }
    };

    const toggleProblem = (problemId) => {
        setSelectedProblems(prev =>
            prev.includes(problemId)
                ? prev.filter(p => p !== problemId)
                : [...prev, problemId]
        );
    };

    const handleStartConsultation = async () => {
        if (selectedProblems.length === 0 && !customProblem.trim()) {
            alert('Please select at least one problem or enter a custom problem');
            return;
        }

        setProcessing(true);
        try {
            // Create consultation
            const consultation = await createConsultation({
                student_id: parseInt(id),
                problems: selectedProblems.map(pid => ({ problem_id: pid, notes: null })),
                custom_problem_text: customProblem || null,
                mentor_notes: mentorNotes || null
            });

            setConsultationId(consultation.id);

            // Generate report
            const report = await generateReport(consultation.id);
            setReportGenerated(true);

            alert('Report generated successfully!');
        } catch (err) {
            alert('Failed: ' + (err.response?.data?.detail || err.message));
        } finally {
            setProcessing(false);
        }
    };

    const handleSendReport = async (sendWhatsapp, sendEmail) => {
        if (!consultationId) return;

        setProcessing(true);
        try {
            const result = await sendReport(consultationId, sendWhatsapp, sendEmail);

            if (result.results?.whatsapp?.link) {
                setWhatsappLink(result.results.whatsapp.link);
                window.open(result.results.whatsapp.link, '_blank');
            }

            if (result.results?.email?.status === 'sent') {
                alert('Email sent successfully!');
            }

            // Reload student to show new consultation
            await loadStudent();

            // Reset modal
            setShowConsultation(false);
            setSelectedProblems([]);
            setCustomProblem('');
            setMentorNotes('');
            setConsultationId(null);
            setReportGenerated(false);
        } catch (err) {
            alert('Send failed: ' + (err.response?.data?.detail || err.message));
        } finally {
            setProcessing(false);
        }
    };

    if (loading) {
        return <div className="profile-loading">Loading...</div>;
    }

    return (
        <div className="profile-page">
            <header className="profile-header">
                <button onClick={() => navigate('/mentor')} className="back-btn">← Back</button>
                <div className="profile-title">
                    <h1>{student.name}</h1>
                    <span className="student-code">{student.student_id}</span>
                </div>
                <button
                    className="new-session-btn"
                    onClick={() => setShowConsultation(true)}
                >
                    💬 New Session
                </button>
            </header>

            <main className="profile-content">
                {/* Contact Info */}
                <div className="info-card">
                    <div className="card-header">
                        <h2>📞 Contact Info</h2>
                        <button onClick={() => setEditing(!editing)} className="edit-btn">
                            {editing ? '✕' : '✏️ Edit'}
                        </button>
                    </div>

                    {editing ? (
                        <div className="edit-form">
                            <div className="form-row">
                                <label>Phone (WhatsApp)</label>
                                <input
                                    type="tel"
                                    value={editForm.phone}
                                    onChange={e => setEditForm({ ...editForm, phone: e.target.value })}
                                    placeholder="+91 98765 43210"
                                />
                            </div>
                            <div className="form-row">
                                <label>Email</label>
                                <input
                                    type="email"
                                    value={editForm.email}
                                    onChange={e => setEditForm({ ...editForm, email: e.target.value })}
                                    placeholder="email@example.com"
                                />
                            </div>
                            <button onClick={handleSaveContact} className="save-btn">Save</button>
                        </div>
                    ) : (
                        <div className="contact-display">
                            <p><strong>Phone:</strong> {student.phone || 'Not set'}</p>
                            <p><strong>Email:</strong> {student.email || 'Not set'}</p>
                            <p className="recommendation">
                                💡 Recommend student to name PDFs as: <code>{student.student_id}</code>
                            </p>
                        </div>
                    )}
                </div>

                {/* Performance Stats */}
                <div className="stats-card">
                    <h2>📊 Performance</h2>
                    <div className="perf-stats">
                        <div className="perf-stat">
                            <span className="perf-value">{student.stats?.total_exams || 0}</span>
                            <span className="perf-label">Exams</span>
                        </div>
                        <div className="perf-stat">
                            <span className="perf-value">{student.stats?.average_percentage || 'N/A'}%</span>
                            <span className="perf-label">Average</span>
                        </div>
                        <div className="perf-stat">
                            <span className={`perf-value trend-${student.stats?.trend}`}>
                                {student.stats?.trend === 'improving' ? '📈' :
                                    student.stats?.trend === 'declining' ? '📉' : '➡️'}
                            </span>
                            <span className="perf-label">Trend</span>
                        </div>
                        <div className="perf-stat">
                            <span className="perf-value">{student.stats?.total_consultations || 0}</span>
                            <span className="perf-label">Sessions</span>
                        </div>
                    </div>
                </div>

                {/* Exams Table */}
                <div className="exams-card">
                    <h2>📝 Exam History</h2>
                    {student.exams?.length === 0 ? (
                        <p className="empty-text">No exams recorded yet</p>
                    ) : (
                        <table className="exams-table">
                            <thead>
                                <tr>
                                    <th>Exam</th>
                                    <th>Subject</th>
                                    <th>Date</th>
                                    <th>Score</th>
                                    <th>%</th>
                                </tr>
                            </thead>
                            <tbody>
                                {student.exams?.map(exam => (
                                    <tr key={exam.id}>
                                        <td>{exam.exam_name}</td>
                                        <td>{exam.subject || '-'}</td>
                                        <td>{exam.exam_date ? new Date(exam.exam_date).toLocaleDateString() : '-'}</td>
                                        <td>{exam.obtained_marks}/{exam.total_marks}</td>
                                        <td className={exam.percentage >= 60 ? 'good' : exam.percentage >= 40 ? 'avg' : 'poor'}>
                                            {exam.percentage?.toFixed(1)}%
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>

                {/* Consultation History */}
                <div className="consultations-card">
                    <h2>💬 Consultation History</h2>
                    {student.consultations?.length === 0 ? (
                        <p className="empty-text">No sessions yet</p>
                    ) : (
                        <div className="consultations-list">
                            {student.consultations?.map(c => (
                                <div key={c.id} className="consultation-item">
                                    <div className="consult-header">
                                        <span className="consult-date">
                                            {new Date(c.date).toLocaleDateString()}
                                        </span>
                                        <span className={`consult-status status-${c.delivery_status}`}>
                                            {c.delivery_status}
                                        </span>
                                    </div>
                                    <div className="consult-problems">
                                        {c.problems?.map((p, i) => (
                                            <span key={i} className="problem-tag">
                                                {problems.flatMap(cat => cat.problems).find(pr => pr.id === p.problem_id)?.title || 'Unknown'}
                                            </span>
                                        ))}
                                        {c.custom_problem && <span className="problem-tag custom">{c.custom_problem}</span>}
                                    </div>
                                    {c.solution_preview && (
                                        <p className="consult-solution">{c.solution_preview}</p>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </main>

            {/* Consultation Modal */}
            {showConsultation && (
                <div className="modal-overlay" onClick={() => !processing && setShowConsultation(false)}>
                    <div className="consultation-modal" onClick={e => e.stopPropagation()}>
                        <h2>New Consultation Session</h2>
                        <p className="modal-subtitle">Select problems identified in today's session</p>

                        {!reportGenerated ? (
                            <>
                                <div className="problems-selection">
                                    {problems.map(category => (
                                        <div key={category.id} className="problem-category">
                                            <h3>{category.icon} {category.name}</h3>
                                            <div className="problem-options">
                                                {category.problems.map(problem => (
                                                    <label key={problem.id} className="problem-option">
                                                        <input
                                                            type="checkbox"
                                                            checked={selectedProblems.includes(problem.id)}
                                                            onChange={() => toggleProblem(problem.id)}
                                                        />
                                                        <span>{problem.title}</span>
                                                    </label>
                                                ))}
                                            </div>
                                        </div>
                                    ))}
                                </div>

                                <div className="form-group">
                                    <label>Other Problem (if not listed above)</label>
                                    <textarea
                                        value={customProblem}
                                        onChange={e => setCustomProblem(e.target.value)}
                                        placeholder="Describe the problem..."
                                        rows={2}
                                    />
                                </div>

                                <div className="form-group">
                                    <label>Mentor Notes (for report context)</label>
                                    <textarea
                                        value={mentorNotes}
                                        onChange={e => setMentorNotes(e.target.value)}
                                        placeholder="Any specific observations or context..."
                                        rows={2}
                                    />
                                </div>

                                <div className="modal-actions">
                                    <button onClick={() => setShowConsultation(false)} className="cancel-btn" disabled={processing}>
                                        Cancel
                                    </button>
                                    <button onClick={handleStartConsultation} className="generate-btn" disabled={processing}>
                                        {processing ? '⏳ Generating...' : '✨ Generate Report'}
                                    </button>
                                </div>
                            </>
                        ) : (
                            <div className="report-ready">
                                <div className="success-icon">✅</div>
                                <h3>Report Generated!</h3>
                                <p>How would you like to send it?</p>

                                <div className="send-options">
                                    <button
                                        className="send-btn whatsapp"
                                        onClick={() => handleSendReport(true, false)}
                                        disabled={processing || !student.phone}
                                    >
                                        📱 Send via WhatsApp
                                    </button>
                                    <button
                                        className="send-btn email"
                                        onClick={() => handleSendReport(false, true)}
                                        disabled={processing || !student.email}
                                    >
                                        📧 Send via Email
                                    </button>
                                    <button
                                        className="send-btn both"
                                        onClick={() => handleSendReport(true, true)}
                                        disabled={processing || (!student.phone && !student.email)}
                                    >
                                        📲 Send Both
                                    </button>
                                </div>

                                {(!student.phone || !student.email) && (
                                    <p className="warning-text">
                                        ⚠️ {!student.phone && 'Phone'}{!student.phone && !student.email && ' and '}{!student.email && 'Email'} not set for this student
                                    </p>
                                )}

                                <button
                                    className="skip-btn"
                                    onClick={() => {
                                        setShowConsultation(false);
                                        loadStudent();
                                    }}
                                >
                                    Skip Sending (Save Only)
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

export default StudentProfile;
