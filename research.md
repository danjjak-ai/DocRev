# DocRev 워크스페이스 상세 분석 보고서

본 보고서는 `DocRev` 워크스페이스의 프론트엔드, 백엔드 구조 및 아키텍처, 데이터 흐름에 대한 상세 분석 결과를 담고 있습니다.

## 1. 시스템 개요
**DocRev**는 AI 기반의 다국어 PDF 리뷰 및 주석 플랫폼입니다. 사용자가 업로드한 PDF 문서를 분석하여 특정 금지어(NG Words)나 영업 가이드라인 위반 사항을 식별하고 제안을 제공하며, RAG(Retrieval-Augmented Generation)를 통해 문서 내용에 대한 Q&A 챗봇 기능을 제공합니다.
- **백엔드**: Python, Flask, PyMuPDF(fitz), LangChain, Google Gemini API, ChromaDB
- **프론트엔드**: HTML, Vanilla JavaScript, Tailwind CSS, PDF.js
- **지원 언어**: 한국어(KO), 일본어(JA), 영어(EN)

## 2. 주요 디렉토리 및 파일 구조
- `backend.py`: 메인 Flask 서버. 애플리케이션의 핵심 로직과 모든 API 엔드포인트 포함.
- `pdf_comment_workspace.html` & `clean_version.html`: 메인 PDF 뷰어 및 주석 작성 UI.
- `ng_words_management.html`: 금지어 관리를 위한 관리자 대시보드.
- `rag_management.html`: RAG(참조 문서) 관리를 위한 관리자 대시보드.
- `prompt_management.html`: 다국어 AI 프롬프트 설정을 위한 관리자 대시보드.
- `config/`: 설정 및 데이터 저장 디렉토리.
  - `ng_words_dataset.json`: 금지어 및 가이드라인 데이터.
  - `prompts.json`: 다국어 프롬프트 템플릿 데이터.
  - `ReferenceDoc/`: RAG를 위한 원본 참조 PDF 문서가 저장되는 폴더.
  - `vector_store/`: LangChain의 Chroma 벡터 데이터베이스가 저장되는 폴더.

## 3. 프론트엔드 아키텍처
프론트엔드는 SPA(Single Page Application) 프레임워크 없이 순수 HTML과 JavaScript, Tailwind CSS 기반으로 작성되었습니다.

### 3.1. 다국어 지원 방식
- URL 해시(`target` selector `#variant-kr`, `#variant-jp`, `#variant-en`)와 CSS 선택자를 활용하여 SPA 라우팅 없이 한 HTML 파일 내에서 UI의 언어를 전환합니다. 
- JavaScript 내부 상태 관리로 현재 선택된 언어(`currentLang`)를 유지하여 백엔드 API 호출 시 활용합니다.

### 3.2. PDF 렌더링 및 주석
- Mozilla의 `PDF.js`를 사용하여 `<canvas>` 요소에 PDF를 렌더링합니다.
- 사용자는 영역 선택 또는 텍스트 검색을 통해 수동으로 주석을 추가할 수 있습니다.
- 백엔드의 AI 분석 결과를 받아 PDF 위에 하이라이트 박스(`rect`)를 오버레이하여 시각적으로 표시합니다.

### 3.3. 관리자 대시보드
- **금지어 관리**: `ng_words_management.html`에서 백엔드 REST API(`GET`, `POST`, `PUT`, `DELETE` `/api/ng-words`)를 호출하여 `ng_words_dataset.json`을 읽고 씁니다.
- **프롬프트 관리**: `prompt_management.html`에서 `/api/prompts` 엔드포인트를 통해 리뷰 및 챗봇 프롬프트를 언어별로 수정하고 저장합니다.
- **RAG 문서 관리**: 참조 문서를 업로드하고, "RAG 재구성" 버튼을 통해 백엔드의 벡터 DB 재생성(`trigger_rag_reconstruction`)을 주기적인 폴링(Polling)으로 상태 업데이트(`get_rag_status`)를 추적합니다.

## 4. 백엔드 아키텍처 및 데이터 흐름
백엔드는 Flask로 구현되어 있으며, 분석 강도에 따라 "단순 리뷰(Level 1)"와 "심층 리뷰(Level 2)" 두 가지 방식을 지원합니다.

### 4.1. PDF 파싱 및 기본 처리
- 사용자가 PDF를 업로드하면 `/upload` 엔드포인트에서 파일 스트림을 받아 처리합니다.
- `PyMuPDF(fitz)`를 사용하여 문서의 페이지 수와 텍스트를 추출합니다.

### 4.2. 단순 리뷰 (Level 1 분석 - Rule-based)
- `config/ng_words_dataset.json`에 정의된 금지어 목록을 순회합니다.
- `PyMuPDF`의 `search_for()` 함수를 사용하여 페이지 내에서 정확하게 일치하는 금지어가 있는지 확인합니다.
- 금지어가 발견되면 일치하는 영역의 좌료(`rect`)와 규칙(`clause`), 제안(`suggestion`) 데이터를 JSON 객체 배열에 담아 응답합니다. (속도가 빠르고 결정론적입니다)

### 4.3. 심층 리뷰 (Level 2 분석 - LLM + RAG)
- **문서 임베딩**: 사용자가 업로드한 문서의 텍스트가 백그라운드 스레드에서 즉시 Chroma 벡터 스토어에 임베딩(`index_pdf_text`)됩니다.
- **RAG 검색**: 기본 검색어(`판매정보제공 가이드라인 허위 과장 비방 금지`)를 Gemini 모델을 통해 언어에 맞게 확장(`expand_query_with_gemini`)한 뒤, 하이브리드 검색(`HuggingFaceEmbeddings` 기반 Vector 검색 + `BM25` 키워드 검색)을 수행하여 관련 있는 참조 지침(`ReferenceDoc`의 Chunk) 7개를 추출합니다. (임베딩 모델: `pkshatech/GLuCoSE-base-ja`)
- **LLM 리뷰**: 검색된 가이드라인과 문서의 전체 텍스트를 결합하여 Gemini(`gemini-2.5-flash`)에 전달합니다. Gemini는 문서 전체에 대해 가이드라인 위반 사항을 JSON 리스트로 출력하도록 프롬프팅되어 있습니다.
- **좌표 매핑 (Fallback Search)**: LLM이 텍스트(quote)만 잡아내고 화면상의 위치(좌표)를 모르기 때문에, 응답받은 `quote` 문자열을 기반으로 다시 `PyMuPDF`를 사용하여 문서 전체를 텍스트 검색(prefix 검색 폴백 포함)해 시각적 하이라이트 박스(`rect`)를 추가합니다.

### 4.4. 문서 Q&A 채팅 (`/chat` 엔드포인트)
- 프론트엔드 채팅 위젯에서 쿼리가 인입되면 백엔드 내부적으로 Gemini를 사용해 쿼리를 확장(Query Expansion)한 후 벡터 스토어 검색을 수행합니다.
- 추출된 컨텍스트와 사용자의 원문 질문을 Gemini에 전달하여 문서 기반 답변을 생성하여 리턴합니다.

## 5. 종합 평가 및 개선 포인트
- **구조의 장점**: 복잡한 SPA(React/Vue) 프레임워크 없이도 세련된 멀티 UI를 구성했고, LangChain과 Hybrid Search(BM25+Vector) 도입으로 RAG 품질을 끌어올림으로써 생산성을 갖췄습니다.
- **성능 고려사항**: `/upload`에서 Level 2 분석 도중 RAG 및 LLM Inference 타임이 병목이 될 수 있으며, 특히 긴 문서의 경우 전체 텍스트가 Gemini 모델 Context Window에 다 들어갈 수 있도록 Token limit 모니터링이 필요할 수 있습니다.
- **좌표 매핑 견고성**: 심층 리뷰 시 LLM이 생성한 `quote`를 `PyMuPDF`로 역검색하는 방식은, 원본 텍스트의 줄바꿈이나 공백 문자가 달라지면 텍스트 검색에 실패하여 하이라이팅을 못할 확률이 있습니다. 문자 수준 정규화 검색이나 OCR 지원이 고려될 수 있습니다.
