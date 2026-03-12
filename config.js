// API Configuration
// For local development, use http://localhost:5000
// For production, replace with your Cloud Run URL after deployment
const API_BASE_URL = window.ENV_BACKEND_URL || (
    (
        window.location.hostname === 'localhost' ||
        window.location.hostname === '127.0.0.1' ||
        window.location.hostname.startsWith('192.168.') ||
        window.location.port === '8080'
    )
        ? 'http://localhost:5000'
        : 'https://docrev-backend-m2gy5tp2kq-du.a.run.app'
);

console.log('Using API_BASE_URL:', API_BASE_URL);
