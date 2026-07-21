const normalizeBaseUrl = (value) => {
    if (!value) return '';
    return value.replace(/\/$/, '');
};

export const CHECKER_API_BASE = normalizeBaseUrl(import.meta.env.VITE_CHECKER_API_URL);
export const SETTER_API_BASE = normalizeBaseUrl(import.meta.env.VITE_SETTER_API_URL);
export const MENTOR_API_BASE = normalizeBaseUrl(import.meta.env.VITE_MENTOR_API_URL);
