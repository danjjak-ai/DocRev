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
        {"id": "guideline", "name": "蛹ｻ逋ら畑蛹ｻ阮ｬ蜩√・雋ｩ螢ｲ諠・ｱ謠蝉ｾ帶ｴｻ蜍輔↓髢｢縺吶ｋ繧ｬ繧､繝峨Λ繧､繝ｳ"},
        {"id": "d5e058f4", "name": "Test RAG Group"}
    ],
    ng: [
        {"id": "guideline", "name": "蛹ｻ逋ら畑蛹ｻ阮ｬ蜩・},
        {"id": "e1a09f22", "name": "蛹ｻ逋ら畑蛹ｻ阮ｬ蜩√・雋ｩ螢ｲ諠・ｱ謠蝉ｾ帶ｴｻ蜍・},
        {"id": "5e1ce10f", "name": "Test NG Group"}
    ],
    prompt: [
        {"id": "guideline", "name": "蛹ｻ逋ら畑蛹ｻ阮ｬ蜩√・雋ｩ螢ｲ諠・ｱ謠蝉ｾ帶ｴｻ蜍・},
        {"id": "3d5ac013", "name": "Test Prompt Group"},
        {"id": "e7ed39b1", "name": "ddddd"}
    ]
};

console.log('Using API_BASE_URL:', API_BASE_URL);
