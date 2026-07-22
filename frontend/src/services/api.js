/**
 * API Service for CheckerAI Backend
 * 
 * Uses relative URLs by default so Vite/nginx can proxy to CheckerAI.
 * Set VITE_CHECKER_API_URL to call a backend directly.
 */

import axios from 'axios';
import { CHECKER_API_BASE } from './config';

// Create axios instance
const api = axios.create({
    baseURL: CHECKER_API_BASE,
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
    // If id is a pipeline task UUID (length > 10)
    if (typeof id === 'string' && id.length > 10) {
        const response = await api.get(`/api/pipelines/student/${id}`);
        return response.data;
    }
    const response = await api.get(`/api/students/${id}`);
    return response.data;
};

export const downloadResultPdf = async (studentId) => {
    if (typeof studentId === 'string' && studentId.length > 10) {
        const response = await api.get(`/api/pipelines/download/${studentId}/grading_report`, {
            responseType: 'blob',
        });
        return response.data;
    }
    const response = await api.get(`/api/students/${studentId}/result-pdf`, {
        responseType: 'blob',
    });
    return response.data;
};

export const downloadCheckedCopyPdf = async (studentId) => {
    if (typeof studentId === 'string' && studentId.length > 10) {
        const response = await api.get(`/api/pipelines/download/${studentId}/checked_copy`, {
            responseType: 'blob',
        });
        return response.data;
    }
    const response = await api.get(`/api/students/${studentId}/checked-copy-pdf`, {
        responseType: 'blob',
    });
    return response.data;
};

/**
 * Fetch the annotation manifest summary for the edit page.
 * Returns { grand_total, questions: { key: { marks_obtained, marks_total, feedback_text, ... } } }
 */
export const getAnnotationManifest = async (studentId) => {
    if (typeof studentId === 'string' && studentId.length > 10) {
        const response = await api.get(`/api/pipelines/manifest/${studentId}`);
        return response.data;
    }
    const response = await api.get(`/api/students/${studentId}/manifest`);
    return response.data;
};

/**
 * Apply corrections and download the patched checked-copy PDF as a Blob.
 *
 * corrections: {
 *   "SectionB__Q1": { marks_obtained: 5, feedback_text: "..." },
 *   ...
 * }
 */
export const patchCheckedCopy = async (studentId, corrections) => {
    if (typeof studentId === 'string' && studentId.length > 10) {
        const response = await api.post(
            `/api/pipelines/patch/${studentId}`,
            { corrections },
            { responseType: 'blob' }
        );
        return response.data;
    }
    const response = await api.post(
        `/api/students/${studentId}/patch`,
        { corrections },
        { responseType: 'blob' }
    );
    return response.data;
};

// ── Pipeline APIs ────────────────────────────────────────────────────────────

/**
 * Fetch the full paper catalog:
 * { "Final": { "AA": { "Mock": [...], "Portionwise": [...] } } }
 */
export const getPaperCatalog = async () => {
    const response = await api.get('/api/pipelines/catalog');
    return response.data;
};

/**
 * Launch the Old-Papers (Claude) pipeline.
 * Returns { task_id, status }
 */
export const runOldPipeline = async (studentName, qpPdf, saPdf, asPdf) => {
    const fd = new FormData();
    fd.append('student_name', studentName);
    fd.append('qp_pdf', qpPdf);
    fd.append('sa_pdf', saPdf);
    fd.append('as_pdf', asPdf);
    const response = await api.post('/api/pipelines/run/old', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 30000,   // just for the initial kick-off
    });
    return response.data;
};

/**
 * Launch the New-Papers (FT) pipeline.
 * Returns { task_id, status }
 */
export const runNewPipeline = async (studentName, ftPaperPath, asPdf) => {
    const fd = new FormData();
    fd.append('student_name', studentName);
    fd.append('ft_paper_path', ftPaperPath);
    fd.append('as_pdf', asPdf);
    const response = await api.post('/api/pipelines/run/new', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 30000,
    });
    return response.data;
};

/**
 * Launch the Feedback pipeline.
 * Returns { task_id, status }
 */
export const runFeedbackPipeline = async (studentName, saPdf, asPdf, marksJsonStr) => {
    const fd = new FormData();
    fd.append('student_name', studentName);
    fd.append('sa_pdf', saPdf);
    fd.append('as_pdf', asPdf);
    fd.append('marks_json_str', marksJsonStr);
    const response = await api.post('/api/pipelines/run/feedback', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 30000,
    });
    return response.data;
};

/**
 * Poll for a pipeline job's current status.
 * Returns { stage, message, status, checked_copy_ready, grading_report_ready, ... }
 */
export const getPipelineStatus = async (taskId) => {
    const response = await api.get(`/api/pipelines/status/${taskId}`);
    return response.data;
};

/**
 * Download a finished pipeline result file as a Blob.
 * fileType: "checked_copy" | "grading_report"
 */
export const downloadPipelineResult = async (taskId, fileType) => {
    const response = await api.get(
        `/api/pipelines/download/${taskId}/${fileType}`,
        { responseType: 'blob' }
    );
    return response.data;
};

export default api;
