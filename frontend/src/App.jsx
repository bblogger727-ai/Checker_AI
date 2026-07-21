import { useState, useEffect, createContext, useContext } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import ExamDetail from './pages/ExamDetail';
import Setter from './pages/Setter';
import PaperEditor from './pages/PaperEditor';
import Mentor from './pages/Mentor';
import StudentProfile from './pages/StudentProfile';
import CheckedPaper from './pages/CheckedPaper';
import EditCheckedCopy from './pages/EditCheckedCopy';
import './App.css';

// Auth Context
export const AuthContext = createContext(null);

export const useAuth = () => useContext(AuthContext);

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if admin is logged in
    const savedUser = localStorage.getItem('admin_user');
    if (savedUser) {
      setUser(JSON.parse(savedUser));
    }
    setLoading(false);
  }, []);

  const login = (userData) => {
    localStorage.setItem('admin_user', JSON.stringify(userData));
    setUser(userData);
  };

  const logout = () => {
    localStorage.removeItem('admin_user');
    setUser(null);
  };

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="spinner"></div>
        <p>Loading...</p>
      </div>
    );
  }

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      <BrowserRouter>
        <Routes>
          <Route
            path="/login"
            element={user ? <Navigate to="/" /> : <Login />}
          />
          {/* CheckerAI Routes */}
          <Route
            path="/"
            element={user ? <Dashboard /> : <Navigate to="/login" />}
          />
          <Route
            path="/exam/:id"
            element={user ? <ExamDetail /> : <Navigate to="/login" />}
          />
          <Route
            path="/checked-paper/:id"
            element={user ? <CheckedPaper /> : <Navigate to="/login" />}
          />
          <Route
            path="/checked-paper/:id/edit"
            element={user ? <EditCheckedCopy /> : <Navigate to="/login" />}
          />
          {/* SetterAI Routes */}
          <Route
            path="/setter"
            element={user ? <Setter /> : <Navigate to="/login" />}
          />
          <Route
            path="/setter/edit/:id"
            element={user ? <PaperEditor /> : <Navigate to="/login" />}
          />
          {/* MentorAI Routes */}
          <Route
            path="/mentor"
            element={user ? <Mentor /> : <Navigate to="/login" />}
          />
          <Route
            path="/mentor/student/:id"
            element={user ? <StudentProfile /> : <Navigate to="/login" />}
          />
        </Routes>
      </BrowserRouter>
    </AuthContext.Provider>
  );
}

export default App;
