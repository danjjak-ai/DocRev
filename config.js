// API Configuration
// For local development, use https://docrev-backend-m2gy5tp2kq-du.a.run.app
// For production, replace with your Cloud Run URL after deployment
const API_BASE_URL = window.ENV_BACKEND_URL || (
    (
        !window.location.hostname ||
        window.location.hostname === 'localhost' ||
        window.location.hostname === '127.0.0.1' ||
        window.location.hostname.startsWith('192.168.') ||
        window.location.protocol === 'file:' ||
        window.location.port === '5000'
    )
        ? 'https://docrev-backend-m2gy5tp2kq-du.a.run.app'
        : 'https://docrev-backend-m2gy5tp2kq-du.a.run.app'
);

const INITIAL_GROUPS = {
    rag: [
        {"id": "default", "name": "・ｰ・ｸ ・ｸ・ｹ (Default)"}
    ],
    ng: [
        {"id": "default", "name": "・ｰ・ｸ ・溢ｧ・ｴ (Default)"}
    ],
    prompt: [
        {"id": "default", "name": "・ｰ・ｸ 嵓・｡ｬ嵓・敢 (Default)"}
    ]
};

console.log('Using API_BASE_URL:', API_BASE_URL);
