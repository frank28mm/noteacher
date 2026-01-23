import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export const apiClient = axios.create({
    baseURL: API_BASE_URL,
    timeout: 60000,
    headers: {
        'Content-Type': 'application/json',
    },
});

apiClient.interceptors.request.use((config) => {
    const headers = config.headers || {};
    const adminToken = localStorage.getItem('admin_token');
    
    if (adminToken) {
        headers['X-Admin-Token'] = adminToken;
    }

    // Disable caching for GET requests
    if (config.method === 'get') {
        config.params = {
            ...config.params,
            _t: Date.now(),
        };
    }

    return { ...config, headers };
});

apiClient.interceptors.response.use(
    (response) => response,
    (error) => {
        // Admin handles 401/403 in components
        return Promise.reject(error);
    }
);
