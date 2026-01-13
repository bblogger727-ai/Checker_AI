import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../App';
import {
    getDashboardStats,
    getStudents,
    getRecentActivity,
    getPendingFollowups,
    createStudent
} from '../services/mentorApi';
import './Mentor.css';

function Mentor() {
    const { user, logout } = useAuth();
    const navigate = useNavigate();

    const [stats, setStats] = useState(null);
    const [students, setStudents] = useState([]);
    const [recentActivity, setRecentActivity] = useState([]);
    const [pendingFollowups, setPendingFollowups] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');

    // Create student modal
    const [showCreate, setShowCreate] = useState(false);
    const [newStudent, setNewStudent] = useState({ name: '', phone: '', email: '' });
    const [creating, setCreating] = useState(false);

    useEffect(() => {
        loadData();
    }, []);

    useEffect(() => {
        const timer = setTimeout(() => {
            loadStudents();
        }, 300);
        return () => clearTimeout(timer);
    }, [search]);

    const loadData = async () => {
        try {
            const [statsData, studentsData, activityData, followupsData] = await Promise.all([
                getDashboardStats(),
                getStudents(),
                getRecentActivity(5),
                getPendingFollowups()
            ]);
            setStats(statsData);
            setStudents(studentsData.students || []);
            setRecentActivity(activityData);
            setPendingFollowups(followupsData);
        } catch (err) {
            console.error('Failed to load data:', err);
        } finally {
            setLoading(false);
        }
    };

    const loadStudents = async () => {
        try {
            const data = await getStudents(search);
            setStudents(data.students || []);
        } catch (err) {
            console.error('Failed to load students:', err);
        }
    };

    const handleCreateStudent = async (e) => {
        e.preventDefault();
        setCreating(true);
        try {
            const result = await createStudent(newStudent);
            alert(`Student created: ${result.student_id}`);
            setShowCreate(false);
            setNewStudent({ name: '', phone: '', email: '' });
            loadData();
        } catch (err) {
            alert('Failed to create student');
        } finally {
            setCreating(false);
        }
    };

    return (
        <div className="mentor-page">
            <header className="header">
                <div className="header-left">
                    <button onClick={() => navigate('/')} className="back-btn">← Checker</button>
                    <span className="logo-icon">👨‍🏫</span>
                    <h1>MentorAI</h1>
                </div>
                <div className="header-right">
                    <span className="user-name">{user?.name || 'Admin'}</span>
                    <button onClick={logout} className="logout-btn">Logout</button>
                </div>
            </header>

            <main className="main-content">
                {/* Stats Cards */}
                {stats && (
                    <div className="stats-grid">
                        <div className="stat-card">
                            <div className="stat-value">{stats.total_students}</div>
                            <div className="stat-label">Total Students</div>
                        </div>
                        <div className="stat-card">
                            <div className="stat-value">{stats.consultations_this_week}</div>
                            <div className="stat-label">Sessions This Week</div>
                        </div>
                        <div className="stat-card">
                            <div className="stat-value">{stats.pending_followup_count}</div>
                            <div className="stat-label">Pending Follow-ups</div>
                        </div>
                        <div className="stat-card">
                            <div className="stat-value">{stats.average_performance ? `${stats.average_performance}%` : 'N/A'}</div>
                            <div className="stat-label">Avg Performance</div>
                        </div>
                    </div>
                )}

                <div className="mentor-grid">
                    {/* Students List */}
                    <div className="students-section">
                        <div className="section-header">
                            <h2>Students ({students.length})</h2>
                            <button onClick={() => setShowCreate(true)} className="add-btn">+ Add Student</button>
                        </div>

                        <input
                            type="text"
                            className="search-input"
                            placeholder="Search by name or ID..."
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                        />

                        {loading ? (
                            <div className="loading">Loading...</div>
                        ) : students.length === 0 ? (
                            <div className="empty-state">
                                <div className="empty-icon">👨‍🎓</div>
                                <p>No students yet</p>
                            </div>
                        ) : (
                            <div className="students-list">
                                {students.map(student => (
                                    <div
                                        key={student.id}
                                        className="student-card"
                                        onClick={() => navigate(`/mentor/student/${student.id}`)}
                                    >
                                        <div className="student-info">
                                            <div className="student-name">{student.name}</div>
                                            <div className="student-id">{student.student_id}</div>
                                        </div>
                                        <div className="student-stats">
                                            <span className="stat-item">📝 {student.exam_count} exams</span>
                                            <span className="stat-item">💬 {student.consultation_count} sessions</span>
                                            {student.average_percentage && (
                                                <span className="stat-item avg-pct">📊 {student.average_percentage}%</span>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Sidebar */}
                    <div className="sidebar">
                        {/* Pending Follow-ups */}
                        <div className="sidebar-section">
                            <h3>⚠️ Pending Follow-ups</h3>
                            {pendingFollowups.length === 0 ? (
                                <p className="empty-text">All caught up!</p>
                            ) : (
                                <div className="followup-list">
                                    {pendingFollowups.slice(0, 5).map(f => (
                                        <div
                                            key={f.student_id}
                                            className="followup-item"
                                            onClick={() => navigate(`/mentor/student/${f.student_id}`)}
                                        >
                                            <span className="followup-name">{f.name}</span>
                                            <span className="followup-days">
                                                {f.days_since ? `${f.days_since}d ago` : 'New'}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* Recent Activity */}
                        <div className="sidebar-section">
                            <h3>🕐 Recent Sessions</h3>
                            {recentActivity.length === 0 ? (
                                <p className="empty-text">No sessions yet</p>
                            ) : (
                                <div className="activity-list">
                                    {recentActivity.map(a => (
                                        <div key={a.id} className="activity-item">
                                            <span className="activity-name">{a.student_name}</span>
                                            <span className="activity-date">
                                                {new Date(a.date).toLocaleDateString()}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </main>

            {/* Create Student Modal */}
            {showCreate && (
                <div className="modal-overlay" onClick={() => setShowCreate(false)}>
                    <div className="modal" onClick={e => e.stopPropagation()}>
                        <h2>Add New Student</h2>
                        <form onSubmit={handleCreateStudent}>
                            <div className="form-group">
                                <label>Name *</label>
                                <input
                                    type="text"
                                    value={newStudent.name}
                                    onChange={e => setNewStudent({ ...newStudent, name: e.target.value })}
                                    placeholder="Full name"
                                    required
                                />
                            </div>
                            <div className="form-group">
                                <label>Phone (WhatsApp)</label>
                                <input
                                    type="tel"
                                    value={newStudent.phone}
                                    onChange={e => setNewStudent({ ...newStudent, phone: e.target.value })}
                                    placeholder="+91 98765 43210"
                                />
                            </div>
                            <div className="form-group">
                                <label>Email</label>
                                <input
                                    type="email"
                                    value={newStudent.email}
                                    onChange={e => setNewStudent({ ...newStudent, email: e.target.value })}
                                    placeholder="student@email.com"
                                />
                            </div>
                            <div className="modal-actions">
                                <button type="button" onClick={() => setShowCreate(false)} className="cancel-btn">Cancel</button>
                                <button type="submit" disabled={creating} className="submit-btn">
                                    {creating ? 'Creating...' : 'Add Student'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}

export default Mentor;
