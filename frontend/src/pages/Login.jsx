import { useState } from 'react';
import { useAuth } from '../App';
import './Login.css';

// Credentials are checked on the server (auth-gate); none are kept in this file.

function Login() {
    const { login } = useAuth();
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            const response = await fetch('/auth-gate/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            if (response.ok) {
                login(await response.json());
            } else if (response.status === 429) {
                setError('Too many attempts. Please wait a minute and try again.');
            } else {
                setError('Invalid username or password');
            }
        } catch {
            setError('Could not reach the server. Please try again.');
        }

        setLoading(false);
    };

    return (
        <div className="login-container">
            <div className="login-card">
                <div className="login-header">
                    <div className="logo">
                        <span className="logo-icon">🎓</span>
                        <h1>Student Evaluator</h1>
                    </div>
                    <p>AI-Powered Student Management System</p>
                    <div className="module-badges">
                        <span className="module-badge checker">✓ CheckerAI</span>
                        <span className="module-badge setter">📝 SetterAI</span>
                        <span className="module-badge mentor">👨‍🏫 MentorAI</span>
                    </div>
                </div>

                <form onSubmit={handleSubmit} className="login-form">
                    <h2>Admin Login</h2>

                    {error && <div className="error-message">{error}</div>}

                    <div className="form-group">
                        <label htmlFor="username">Username</label>
                        <input
                            type="text"
                            id="username"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            placeholder="Enter username"
                            required
                            autoComplete="username"
                        />
                    </div>

                    <div className="form-group">
                        <label htmlFor="password">Password</label>
                        <input
                            type="password"
                            id="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder="Enter password"
                            required
                            autoComplete="current-password"
                        />
                    </div>

                    <button type="submit" className="submit-btn" disabled={loading}>
                        {loading ? 'Signing in...' : 'Sign In'}
                    </button>
                </form>
            </div>
        </div>
    );
}

export default Login;
