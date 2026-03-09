// API Configuration
// For local development, use http://localhost:5000
// For production, replace with your Cloud Run URL after deployment
const API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:5000'
    : 'https://docrev-backend-954613353797.asia-northeast3.run.app'; // Leave empty for now, or put Cloud Run URL here

console.log('Using API_BASE_URL:', API_BASE_URL);
