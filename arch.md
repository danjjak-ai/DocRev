# 프로젝트 디렉토리 구조 및 파일 설명

```
DocRev/
├─ .env                 # 로컬 환경 변수 파일 (GEMINI_API_KEY 등)
├─ backend.py           # Flask 기반 백엔드 서버
├─ Dockerfile           # Cloud Run 배포용 이미지 빌드 스크립트
├─ requirements.txt     # Python 의존성 목록
├─ deploy.bat           # GCP 배포 자동화 배치 스크립트
├─ deploy_config.bat    # 배포에 필요한 파라미터 (PROJECT_ID, REGION, SERVICE_NAME 등)
├─ firebase.json        # Firebase Hosting 설정 파일
├─ .firebaserc          # Firebase 프로젝트 매핑 파일
├─ config.js            # 프론트엔드 설정 파일 (API_BASE_URL, SERVICE_URL 등)
├─ index.html           # 메인 프론트엔드 페이지 (HTML)
├─ rag_management.html  # RAG 관리 화면
├─ prompt_management.html # 프롬프트 관리 화면
├─ ng_words_management.html # NG 워드 관리 화면
├─ pdf_comment_workspace.html # PDF 주석 작업 화면
├─ research.md          # 프로젝트 관련 조사·메모 파일
└─ arch.md              # **이 파일** – 프로젝트 디렉토리 및 파일 구성 설명
```

## 주요 파일 설명
- **`.env`**: 로컬에서 `GEMINI_API_KEY` 등 비밀 정보를 저장합니다. `deploy.bat`이 이 파일을 읽어 환경 변수를 설정합니다.
- **`backend.py`**: Flask 애플리케이션으로, Cloud Run에 배포됩니다. `PORT` 환경 변수를 사용해 포트를 동적으로 지정합니다.
- **`Dockerfile`**: 백엔드 컨테이너 이미지를 만들기 위한 설정 파일이며, `gcloud run deploy` 명령에서 `--source .` 옵션으로 자동 사용됩니다.
- **`deploy.bat`**: GCP 프로젝트 설정, Cloud Run 배포, 서비스 URL 추출, `config.js` 업데이트, Firebase Hosting 배포까지 일괄 수행합니다.
- **`deploy_config.bat`**: 배포에 필요한 파라미터(`PROJECT_ID`, `REGION`, `SERVICE_NAME`, `GEMINI_API_KEY` 등)를 정의합니다.
- **`firebase.json` / `.firebaserc`**: Firebase Hosting 설정 및 프로젝트 매핑을 정의합니다.
- **`config.js`**: 프론트엔드에서 백엔드 API URL(`API_BASE_URL`)과 Cloud Run 서비스 URL(`SERVICE_URL`)을 관리합니다. `deploy.bat`이 배포 후 자동으로 업데이트합니다.
- **HTML 파일들** (`index.html`, `rag_management.html`, 등): 정적 프론트엔드 페이지이며, `config.js`를 통해 백엔드와 통신합니다.
- **`research.md`**: 개발 과정 중 조사·메모용 마크다운 파일.
- **`arch.md`**: 현재 파일 – 프로젝트 구조와 각 파일 역할을 문서화합니다.

이 구조는 **백엔드 → Cloud Run**, **프론트엔드 → Firebase Hosting** 로의 배포 흐름을 지원하도록 설계되었습니다. 필요에 따라 파일을 추가하거나 기존 파일을 수정해 확장할 수 있습니다.
