/**
 * API Service for CheckerAI Backend
 * 
 * Uses relative URLs when running in Docker (nginx proxies to backend)
 * Uses localhost:8000 for local development
 */

import axios from 'axios';

// Detect if running in production (no port in URL) or development
const isProduction = !window.location.port || window.location.port === '80';
const API_BASE = isProduction ? '' : 'http://localhost:8000';

// Create axios instance
const api = axios.create({
    baseURL: API_BASE,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Exams
export const getExams = async () => {
    const response = await api.get('/api/exams');
    return response.data;
};

export const getExam = async (id) => {
    const response = await api.get(`/api/exams/${id}`);
    return response.data;
};

export const createExam = async (name, subject, examDate, solutionPdf) => {
    const formData = new FormData();
    formData.append('name', name);
    if (subject) formData.append('subject', subject);
    if (examDate) formData.append('exam_date', examDate);
    formData.append('solution_pdf', solutionPdf);

    const response = await api.post('/api/exams', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
};

export const deleteExam = async (id) => {
    const response = await api.delete(`/api/exams/${id}`);
    return response.data;
};

export const getStudents = async (examId) => {
    const response = await api.get(`/api/exams/${examId}/students`);
    return response.data;
};

// Students
export const uploadStudentPaper = async (examId, studentName, rollNumber, answerPdf) => {
    const formData = new FormData();
    formData.append('exam_id', examId);
    formData.append('student_name', studentName);
    if (rollNumber) formData.append('roll_number', rollNumber);
    formData.append('answer_pdf', answerPdf);

    const response = await api.post('/api/students/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
};

export const getStudent = async (id) => {
    const response = await api.get(`/api/students/${id}`);
    return response.data;
};

export const downloadResultPdf = async (studentId) => {
    const response = await api.get(`/api/students/${studentId}/result-pdf`, {
        responseType: 'blob',
    });
    return response.data;
};

export default api;
