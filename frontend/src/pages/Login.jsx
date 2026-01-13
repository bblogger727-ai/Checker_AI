import { useState } from 'react';
import { useAuth } from '../App';
import './Login.css';

// Single admin credentials
const ADMIN_USERNAME = 'RuchaSarda';
const ADMIN_PASSWORD = 'CA@Rucha';

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

        // Check hardcoded credentials
        if (username === ADMIN_USERNAME && password === ADMIN_PASSWORD) {
            // Set auth state
            login({ name: 'Rucha Sarda', role: 'admin' });
        } else {
            setError('Invalid username or password');
        }

        setLoading(false);
    };

    return (
        <div className="login-container">
            <div className="login-card">
                <div className="login-header">
                    <div className="logo">
                        <span className="logo-icon">✓</span>
                        <h1>CheckerAI</h1>
                    </div>
                    <p>AI-Powered Exam Evaluation System</p>
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
