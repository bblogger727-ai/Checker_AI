/**
 * MentorAI API Service
 * 
 * API calls for student tracking, consultations, and reports.
 */

import axios from 'axios';

const isProduction = !window.location.port || window.location.port === '80';
const API_BASE = isProduction ? '' : 'http://localhost:8002';

const api = axios.create({
    baseURL: API_BASE,
    headers: { 'Content-Type': 'application/json' },
});

// Dashboard
export const getDashboardStats = async () => {
    const response = await api.get('/api/mentor/dashboard/stats');
    return response.data;
};

export const getRecentActivity = async (limit = 10) => {
    const response = await api.get('/api/mentor/dashboard/recent', { params: { limit } });
    return response.data;
};

export const getPendingFollowups = async () => {
    const response = await api.get('/api/mentor/dashboard/pending-followup');
    return response.data;
};

// Students
export const getStudents = async (search = '', limit = 50, offset = 0) => {
    const response = await api.get('/api/mentor/students', {
        params: { search, limit, offset }
    });
    return response.data;
};

export const getStudent = async (studentId) => {
    const response = await api.get(`/api/mentor/students/${studentId}`);
    return response.data;
};

export const createStudent = async (data) => {
    const response = await api.post('/api/mentor/students', data);
    return response.data;
};

export const updateStudent = async (studentId, data) => {
    const response = await api.put(`/api/mentor/students/${studentId}`, data);
    return response.data;
};

export const deleteStudent = async (studentId) => {
    const response = await api.delete(`/api/mentor/students/${studentId}`);
    return response.data;
};

// Problems
export const getProblems = async () => {
    const response = await api.get('/api/mentor/problems');
    return response.data;
};

export const createProblem = async (data) => {
    const response = await api.post('/api/mentor/problems', data);
    return response.data;
};

// Consultations
export const createConsultation = async (data) => {
    const response = await api.post('/api/mentor/consultations', data);
    return response.data;
};

export const getConsultation = async (consultationId) => {
    const response = await api.get(`/api/mentor/consultations/${consultationId}`);
    return response.data;
};

export const generateReport = async (consultationId) => {
    const response = await api.post(`/api/mentor/consultations/${consultationId}/generate-report`);
    return response.data;
};

export const sendReport = async (consultationId, sendWhatsapp, sendEmail) => {
    const response = await api.post(`/api/mentor/consultations/${consultationId}/send`, {
        send_whatsapp: sendWhatsapp,
        send_email: sendEmail
    });
    return response.data;
};

export default api;
