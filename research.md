# DocRev 워크스페이스 상세 분석 및 아키텍처 보고서

본 보고서는 `DocRev` 워크스페이스의 프론트엔드, 백엔드 소스 코드를 빠짐없이 분석하여 실제 구현된 아키텍처, 핵심 로직의 데이터 흐름, 그리고 상세한 개선 포인트를 정리한 문서입니다.

## 1. 시스템 개요 및 기술 스택
**DocRev**는 AI 및 RAG(Retrieval-Augmented Generation) 기술을 기반으로 하는 다국어 지원 PDF 문서 리뷰 및 주석 플랫폼입니다. 사용자가 문서를 업로드하면, 금지어(NG Words) 규칙과 가이드라인을 바탕으로 문서를 자동으로 검토하고, Q&A 챗봇을 통해 문서 내용에 대해 질의응답할 수 있습니다.

*   **백엔드**: Python, Flask, PyMuPDF(fitz), LangChain, Google Gemini API (`gemini-2.5-flash`), Chroma 벡터 DB, HuggingFaceEmbeddings (`pkshatech/GLuCoSE-base-ja`, `intfloat/multilingual-e5-large-instruct` 앙상블)
*   **프론트엔드**: 순수 HTML, Vanilla JavaScript, Tailwind CSS (CDN 연동), PDF.js (CDN 연동), SweetAlert2 (CDN 연동)
*   **지원 언어**: 한국어(KO), 일본어(JA), 영어(EN)

## 2. 주요 파일 및 디렉토리 구조 분석

*   **`backend.py`**: 메인 어플리케이션 서버 파일입니다. PDF 파일 업로드 파싱 로직, AI 분석 파이프라인(Level 1/2), RAG 벡터 DB 구성 스레드, 챗봇 추론, NG 단어/프롬프트 관리 API 등 모든 애플리케이션의 엔드포인트를 포괄하고 있는 핵심 모놀리식 스크립트입니다.
*   **`pdf_comment_workspace.html` & `clean_version.html`**: 메인 기능인 PDF 화면 및 주석 생성 워크스페이스 UI입니다. PDF.js를 통해 `<canvas>`에 문서를 렌더링하며, 사용자의 선택이나 백엔드의 분석 결과 좌표(`rect`)에 따라 Box를 그려줍니다.
*   **`restore_chars.py`**: 다국어 변환 과정에서 손상된 HTML 내의 템플릿 마커(`[[`, `{{` 형태)나 태그 등을 정규식을 통해 올바르게 프론트엔드용으로 복구 및 패치하는 유틸리티 스크립트입니다.
*   **`config.js`**: 프론트엔드가 백엔드 API와 통신할 때 동적으로 바라볼 `API_BASE_URL` (로컬 호스트 및 Cloud Run 환경 분기)이 정의된 설정 파일입니다.
*   **관리자 페이지 화면**:
    *   `ng_words_management.html`: NG(금지) 단어 및 규칙 관리 대시보드
    *   `rag_management.html`: RAG 목적의 참조 문서(PDF) 업로드 및 Vector DB 재구성 트리거 페이지
    *   `prompt_management.html`: 각 기능(단순 리뷰, 심층 리뷰, 챗봇)에 대한 다국어 프롬프트를 조정하는 대시보드
*   **`config/` (데이터 저장소)**:
    *   `ng_words_dataset.json`: NG 단어 규칙 및 제안사항 데이터
    *   `prompts.json`: 다국어 프롬프트 템플릿 데이터
    *   `ReferenceDoc/`: RAG를 위한 원본 참조 PDF 문서가 저장되는 폴더
    *   `vector_store/`: LangChain의 Chroma 벡터 데이터베이스가 영구 저장되는 폴더

## 3. 핵심 기능 구현 상세 및 데이터 흐름

### 3.1. 프론트엔드 다국어(i18n) 처리 아키텍처
현재 시스템은 React/Vue 같은 SPA 프레임워크나 외부 i18n 라이브러리 없이, 순수 HTML 구조에서 CSS와 Vanilla JS만으로 다국어를 지원하고 있습니다.
*   URL의 Hash(`example.html#variant-kr`)를 확인하여, CSS 속성(`display: none` / `display: block`)으로 렌더링될 언어 블록만 화면에 보여줍니다.
*   JavaScript 컨텍스트가 `currentLang` 변수를 관리하여 API 호출 시나 백엔드 요청 시 언어 상태를 동기화합니다.

### 3.2. 단순 리뷰 (Level 1: Rule-based)
*   `ng_words_dataset.json` 파일에 등록된 단순 금지어 목록을 순회합니다.
*   `PyMuPDF (fitz)` 모듈의 `search_for(단어)` 기능을 사용하여 각 대상 페이지 내에서 정확하게 일치하는 텍스트 영역 좌표(`rect`)를 도출합니다.
*   복잡한 추론 과정이 없어 처리 속도가 매우 빠르고 100% 결정론적인(deterministic) 결과를 반환합니다.

### 3.3. 심층 리뷰 (Level 2: LLM + RAG 기반 AI 분석)
1.  **동적 백그라운드 임베딩**: 사용자가 문서를 업로드하면, `index_pdf_text` 스레드를 통해 즉시 문서를 청킹(Chunking)하여 로컬 Chroma DB 임시 컬렉션에 벡터화 시킵니다.
2.  **쿼리 확장 (Query Expansion)**: '가이드라인 위반 여부 확인' 등 시스템에 내장된 기초 탐색 쿼리를 Gemini LLM으로 전달해 해당 텍스트에 어울리도록 쿼리를 한 번 확장합니다.
3.  **하이브리드 검색 (Hybrid Search)**: LangChain의 `EnsembleRetriever`를 사용합니다. ChromaDB를 통한 **Vector Similarity Search**와 `BM25Retriever`를 통한 **Keyword Search**를 앙상블 결합하여 가장 관련성 높은 RAG 참조 가이드라인 청크를 7개 뽑아냅니다.
4.  **LLM 추론**: 추출된 가이드라인과 전체 문서 텍스트를 `gemini-2.5-flash` 모델 프롬프트로 주입합니다. LLM은 문서 내에서 가이드라인을 어긴 특정 원문 텍스트(`quote`)와 그 이유 및 제안 사항을 JSON 리스트로 출력합니다.
5.  **좌표 역매핑 (Fallback Text Search)**: LLM은 공간적 개념(좌표)을 인식하지 못하고 문장(Text)만 반환하므로, 백엔드에서 다시 `PyMuPDF`를 사용하여 대상 문서를 검사하고 반환된 `quote` 문장과 일치하는 시각적 `rect` 좌표를 역으로 찾아 프론트엔드에 전달합니다. (띄어쓰기 예외 대응을 위해 Prefix Search 폴백 로직 포함)

### 3.4. 문서 Q&A 채팅 (`/chat`)
*   사용자의 질문 텍스트가 인입되면 내부적으로 쿼리를 재확장하고, 임의 생성된 대상 문서 벡터 스토어에서 직접 컨텍스트를 검색하여 Gemini 모델로 답변을 생성합니다. (단기 기억에 대한 Session Memory 관리는 프론트엔드에서 주고받는 대화 내역에 의존적으로 동작합니다.)

## 4. 아키텍처 및 소스코드 상세 개선 포인트

현재 워크스페이스는 빠르게 프로토타입을 구성하고 결과를 시각화하는 데 깊게 최적화되어 있으나, 장기적인 유지보수와 스케일 업, 안정성을 위해 아래의 개선 내용 적용이 강력히 권장됩니다.

### 4.1. 보안 및 환경 변수 관리 (Security) - [적용 완료]
*   **구현 내용**: 
    1. Python `python-dotenv` 라이브러리를 통해 `.env` 파일 기반의 설정 관리 체계를 구축했습니다.
    2. API Key, Gemini 모델명(`GEMINI_MODEL`), Flask 포트(`FLASK_PORT`), CORS 허용 오리진(`ALLOWED_ORIGINS`)을 코드 수정 없이 환경 변수로 제어할 수 있습니다.
    3. `backend.py`의 CORS 설정을 와일드카드(`*`)에서 환경 변수에 지정된 특정 도메인만 허용하도록 강화했습니다.
*   **남은 과제**: 
    1. 프론트엔드(`config.js`)의 배포 URL 치환을 빌드 자동화(CI/CD) 과정에 통합하는 작업이 필요합니다.

### 4.2. 백엔드 모듈화 아키텍처 도입 (Micro-structure)
*   **문제점**: `backend.py` 단 한 개의 파일에서 라우팅(Flask Route), PDF 데이터 파싱, LangChain RAG 모델링, LLM Prompt Template 생성, 파일 I/O 처리가 모두 섞여 있는 '모놀리식(Monolithic)' 형태입니다. 파일이 길어 유지보수와 단위 테스트 작성이 극도로 어렵습니다.
*   **개선안**: 다음과 같은 계층화된 디렉토리 구조로 분리 리팩토링이 필요합니다.
    *   `adapters/` (또는 `routes/`): 외부 HTTP 요청 처리 및 리스폰스 (Flask Blueprint 분리)
    *   `services/`: 비즈니스 로직(AI 통합 리뷰 진행, 챗봇 로직, RAG 인덱싱 오케스트레이션)
    *   `repositories/`: `json` 데이터 로드/저장, Chroma DB 접근 분리
    *   `utils/`: PDF 파서, 텍스트 정제 헬퍼, 토큰 카운팅 등

### 4.3. 좌표 역매핑(Fallback Search)의 강건함 추가 (Robustness)
*   **문제점**: 심층 리뷰 시 가장 큰 불안 요소입니다. LLM이 요약 또는 변형해서 반환한 `quote`(인용 문구)를 기반으로 다시 `fitz.search_for`를 수행할 때, 원본 PDF의 숨겨진 유니코드 공백, 줄바꿈, 폰트 이슈로 인해 텍스트 검색에 실패하면 UI 상 화면에 하이라이트 박스를 치지 못합니다.
*   **개선안**:
    1. **정규화 매칭 (Normalized Match)**: `PyMuPDF` 텍스트 데이터의 공백과 특수문자를 Regex 패턴으로 모두 치환한 뒤 Fuzzy Mathing(`difflib`, `FuzzyWuzzy` 등 라이브러리)을 통한 유사도 기반 검색을 도입해야 합니다.
    2. **OCR 파이프라인 보강 (사전 작업)**: 이미지화 된 텍스트 박스로 인한 오류를 최소화하기 위해 PaddleOCR/Tesseract를 통한 전처리 파이프라인 도입이 고려될 수 있습니다.

### 4.4. 성능 및 비동기 작업 병목 해결 (Concurrency)
*   **문제점**: 사용자의 요청과 RAG 재구성(`trigger_rag_reconstruction`), 혹은 대용량 문서에 대한 심층 리뷰 백그라운드 스레드가 리소스를 크게 차지합니다. Flask 기본 서버 방식은 작업이 블로킹될 확률이 높습니다.
*   **개선안**:
    1. 긴 시간이 소요되는 AI 분석 요청과 RAG 구성 작업은 Main Thread에서 벗어나, `Celery` 나 `Redis Queue`, 혹은 클라우드 환경에서는 GCP Pub/Sub와 같은 Message Queue 형태의 백그라운드 Worker 시스템으로 분리해야 합니다.
    2. 프론트엔드는 결과값 폴링(Polling) 뿐만 아니라 장기적으로 WebSockets이나 SSE(Server-Sent Events)로 실시간 분석 과정을 스트리밍 받는 방식으로 최적화 가능합니다.

### 4.5. 에러 처리 및 상태 관리 고도화 (Error Handling)
*   **문제점**: 현재 프론트엔드의 `fetch` 로직은 네트워크 타임아웃이나 백엔드 500 에러 발생 시 범용적인 SweetAlert2 얼럿(예: `Failed to fetch`)만 띄우고 상태가 멈추는 현상이 존재합니다.
*   **개선안**: 
    1. 백엔드에서 `TokenLimitExceeded`, `PDFParsingError`, `SearchFailed` 와 같이 명확한 도메인 에러 클래스를 설계하고 `JSON Response` 내부에 구체적인 에러 Code와 디버깅 메세지를 내려주어야 합니다.
    2. 프론트엔드 레이어에서는 Retry 메커니즘을 부여하고, 화면에 원인이 명시된 안내 팝업을 제공하여 사용자 경험(UX)을 손상시키지 않게 설계합니다.

### 4.6. 다국어 프론트엔드 UI 중복 코드 제거 (DRY Principle)
*   **문제점**: `pdf_comment_workspace.html`, `clean_version.html`, 관리자 대시보드 `.html` 파일마다 모달 UI 로직, 언어 토글 로직, API 호출 코드가 중복되어 배포되어 있습니다.
*   **개선안**: Vanilla JS 스크립트를 여러 파일(`api.js`, `ui.js`, `i18n.js`) 모듈로 캡슐화시켜 HTML `<script src="...">` 로 불러오게 분리하면 코드 중복 방지 및 유지관리가 획기적으로 향상됩니다.
