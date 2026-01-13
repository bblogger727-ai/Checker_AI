import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../App';
import { getSubjects, getTemplates, getPapers, generatePaper, deletePaper } from '../services/setterApi';
import './Setter.css';

function Setter() {
    const { user, logout } = useAuth();
    const navigate = useNavigate();

    const [subjects, setSubjects] = useState([]);
    const [templates, setTemplates] = useState([]);
    const [papers, setPapers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [generating, setGenerating] = useState(false);

    // Form state
    const [selectedSubject, setSelectedSubject] = useState('');
    const [selectedTemplate, setSelectedTemplate] = useState('');
    const [paperTitle, setPaperTitle] = useState('');

    useEffect(() => {
        loadData();
    }, []);

    useEffect(() => {
        if (selectedSubject) {
            loadTemplates(selectedSubject);
        } else {
            setTemplates([]);
        }
    }, [selectedSubject]);

    const loadData = async () => {
        try {
            const [subjectsData, papersData] = await Promise.all([
                getSubjects(),
                getPapers()
            ]);
            setSubjects(subjectsData);
            setPapers(papersData);
        } catch (err) {
            console.error('Failed to load data:', err);
        } finally {
            setLoading(false);
        }
    };

    const loadTemplates = async (subjectId) => {
        try {
            const data = await getTemplates(subjectId);
            setTemplates(data);
        } catch (err) {
            console.error('Failed to load templates:', err);
        }
    };

    const handleGenerate = async () => {
        if (!selectedSubject) {
            alert('Please select a subject');
            return;
        }

        setGenerating(true);
        try {
            const paper = await generatePaper(
                parseInt(selectedSubject),
                selectedTemplate ? parseInt(selectedTemplate) : null,
                paperTitle || null
            );
            navigate(`/setter/edit/${paper.id}`);
        } catch (err) {
            alert('Failed to generate paper: ' + (err.response?.data?.detail || err.message));
        } finally {
            setGenerating(false);
        }
    };

    const handleDelete = async (paperId) => {
        if (!confirm('Delete this paper draft?')) return;
        try {
            await deletePaper(paperId);
            loadData();
        } catch (err) {
            alert('Failed to delete paper');
        }
    };

    const getStatusColor = (status) => {
        switch (status) {
            case 'published': return 'status-published';
            case 'finalized': return 'status-finalized';
            case 'reviewing': return 'status-reviewing';
            default: return 'status-draft';
        }
    };

    return (
        <div className="setter-page">
            <header className="header">
                <div className="header-left">
                    <button onClick={() => navigate('/')} className="back-btn">← Home</button>
                    <span className="logo-icon">🎓</span>
                    <h1>Student Evaluator</h1>
                    <span className="module-indicator setter-indicator">📝 SetterAI</span>
                </div>
                <div className="header-right">
                    <span className="user-name">{user?.name || 'Admin'}</span>
                    <button onClick={logout} className="logout-btn">Logout</button>
                </div>
            </header>

            <main className="main-content">
                {/* Generate Section */}
                <div className="generate-section">
                    <h2>Generate New Paper</h2>
                    <div className="generate-form">
                        <div className="form-row">
                            <div className="form-group">
                                <label>Subject *</label>
                                <select
                                    value={selectedSubject}
                                    onChange={(e) => setSelectedSubject(e.target.value)}
                                >
                                    <option value="">Select Subject</option>
                                    {subjects.map(s => (
                                        <option key={s.id} value={s.id}>{s.name}</option>
                                    ))}
                                </select>
                            </div>

                            <div className="form-group">
                                <label>Paper Template</label>
                                <select
                                    value={selectedTemplate}
                                    onChange={(e) => setSelectedTemplate(e.target.value)}
                                    disabled={!selectedSubject}
                                >
                                    <option value="">Auto (Default Format)</option>
                                    {templates.map(t => (
                                        <option key={t.id} value={t.id}>{t.name}</option>
                                    ))}
                                </select>
                            </div>

                            <div className="form-group">
                                <label>Paper Title (Optional)</label>
                                <input
                                    type="text"
                                    value={paperTitle}
                                    onChange={(e) => setPaperTitle(e.target.value)}
                                    placeholder="e.g., Practice Test - Jan 2026"
                                />
                            </div>
                        </div>

                        <button
                            className="generate-btn"
                            onClick={handleGenerate}
                            disabled={generating || !selectedSubject}
                        >
                            {generating ? '⏳ Generating...' : '✨ Generate Paper'}
                        </button>
                    </div>
                </div>

                {/* Papers List */}
                <div className="papers-section">
                    <h2>Generated Papers ({papers.length})</h2>

                    {loading ? (
                        <div className="loading">Loading papers...</div>
                    ) : papers.length === 0 ? (
                        <div className="empty-state">
                            <div className="empty-icon">📄</div>
                            <h3>No papers yet</h3>
                            <p>Generate your first exam paper above</p>
                        </div>
                    ) : (
                        <div className="papers-table-wrapper">
                            <table className="papers-table">
                                <thead>
                                    <tr>
                                        <th>Title</th>
                                        <th>Subject</th>
                                        <th>Status</th>
                                        <th>Created</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {papers.map(paper => (
                                        <tr key={paper.id}>
                                            <td className="paper-title">{paper.title}</td>
                                            <td>{paper.subject_name}</td>
                                            <td>
                                                <span className={`status-badge ${getStatusColor(paper.status)}`}>
                                                    {paper.status}
                                                </span>
                                            </td>
                                            <td>{new Date(paper.created_at).toLocaleDateString()}</td>
                                            <td>
                                                <div className="action-buttons">
                                                    <button
                                                        className="edit-btn"
                                                        onClick={() => navigate(`/setter/edit/${paper.id}`)}
                                                    >
                                                        {paper.status === 'published' ? '👁️ View' : '✏️ Edit'}
                                                    </button>
                                                    {paper.status !== 'published' && (
                                                        <button
                                                            className="delete-btn"
                                                            onClick={() => handleDelete(paper.id)}
                                                        >
                                                            🗑️
                                                        </button>
                                                    )}
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

                {/* Info Section */}
                {subjects.length === 0 && !loading && (
                    <div className="info-box">
                        <h3>📚 Getting Started</h3>
                        <p>To use SetterAI, you'll need to add:</p>
                        <ol>
                            <li><strong>Subjects</strong> - Add CA subjects with syllabus</li>
                            <li><strong>Questions</strong> - Import PYQs or add questions manually</li>
                            <li><strong>Templates</strong> - Define paper formats (optional)</li>
                        </ol>
                        <p>These can be configured via the API or by providing data files.</p>
                    </div>
                )}
            </main>
        </div>
    );
}

export default Setter;
