/**
 * SetterAI API Service
 * 
 * API calls for paper generation, editing, and publishing.
 */

import axios from 'axios';

const isProduction = !window.location.port || window.location.port === '80';
const API_BASE = isProduction ? '' : 'http://localhost:8001';

const api = axios.create({
    baseURL: API_BASE,
    headers: { 'Content-Type': 'application/json' },
});

// Subjects
export const getSubjects = async () => {
    const response = await api.get('/api/setter/subjects');
    return response.data;
};

export const createSubject = async (data) => {
    const response = await api.post('/api/setter/subjects', data);
    return response.data;
};

// Templates
export const getTemplates = async (subjectId = null) => {
    const params = subjectId ? { subject_id: subjectId } : {};
    const response = await api.get('/api/setter/templates', { params });
    return response.data;
};

export const createTemplate = async (data) => {
    const response = await api.post('/api/setter/templates', data);
    return response.data;
};

// Questions
export const getQuestions = async (filters = {}) => {
    const response = await api.get('/api/setter/questions', { params: filters });
    return response.data;
};

export const createQuestion = async (data) => {
    const response = await api.post('/api/setter/questions', data);
    return response.data;
};

export const bulkCreateQuestions = async (questions) => {
    const response = await api.post('/api/setter/questions/bulk', questions);
    return response.data;
};

// Papers
export const getPapers = async (filters = {}) => {
    const response = await api.get('/api/setter/papers', { params: filters });
    return response.data;
};

export const generatePaper = async (subjectId, templateId = null, title = null, options = null) => {
    const response = await api.post('/api/setter/papers/generate', {
        subject_id: subjectId,
        template_id: templateId,
        title,
        options
    });
    return response.data;
};

export const getPaper = async (paperId) => {
    const response = await api.get(`/api/setter/papers/${paperId}`);
    return response.data;
};

export const updatePaper = async (paperId, editedPaperJson) => {
    const response = await api.put(`/api/setter/papers/${paperId}`, {
        edited_paper_json: editedPaperJson
    });
    return response.data;
};

export const finalizePaper = async (paperId) => {
    const response = await api.post(`/api/setter/papers/${paperId}/finalize`);
    return response.data;
};

export const generateSolution = async (paperId) => {
    const response = await api.post(`/api/setter/papers/${paperId}/generate-solution`);
    return response.data;
};

export const publishPaper = async (paperId) => {
    const response = await api.post(`/api/setter/papers/${paperId}/publish`);
    return response.data;
};

export const deletePaper = async (paperId) => {
    const response = await api.delete(`/api/setter/papers/${paperId}`);
    return response.data;
};

export default api;
