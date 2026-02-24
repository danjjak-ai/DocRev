import re
import os

file_path = r'c:\workspace\DocRev\pdf_comment_workspace.html'

with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. Fix Headers
content = content.replace('PDF ・€奝 ・醐〓・､寬們擽・､', 'PDF 리뷰 워크스페이스')

# 2. Fix placeholder text or extraction errors
content = content.replace('・肥ｶ罹頗 奛作侃孖ｸ・€ ・・慣・壱共.', '텍스트를 추출하지 못했습니다.')

# 3. Fix translations block
ko_translations = """
                                                ko: {
                                                    chatTitle: '문서 분석 Q&A',
                                                    chatPlaceholder: '질문을 입력해주세요...',
                                                    chatGenerating: '답변을 생성 중입니다...',
                                                    chatError: '서버와의 통신 중에 에러가 발생했습니다.',
                                                    chatNoAnswer: '답변을 가져오지 못했습니다.',
                                                    chatWelcome: '안녕하세요! 분석된 문서의 내용에 대해 질문해주세요.',
                                                    aiAnalyzing: '분석 중...',
                                                    aiCompleted: 'AI 분석이 완료되었습니다. 주석 목록을 확인해주세요.',
                                                    noFile: 'PDF 파일을 먼저 업로드해주세요.',
                                                    parsingError: 'AI 응답을 해석하지 못했습니다.',
                                                    existingLabel: '[기존]',
                                                    referenceLabel: '참조 텍스트',
                                                    allPages: '전체 페이지',
                                                    pageTemplate: '{current} / {total} 페이지',
                                                    noExport: '내보낼 주석이 없습니다.',
                                                    enterComment: '주석 내용을 입력해주세요',
                                                    enterKeyword: '검색 키워드를 입력해주세요',
                                                    selectArea: 'PDF 뷰어에서 마우스로 영역을 선택해주세요',
                                                    loadingLib: 'PDF 라이브러리를 로딩 중입니다. 잠시 후 다시 시도해주세요.',
                                                    loadFileFail: '파일을 불러오지 못했습니다.',
                                                    onlyPdf: 'PDF 파일만 업로드 가능합니다.'
                                                },"""

ja_translations = """
                                                ja: {
                                                    chatTitle: 'ドキュメント質疑応答',
                                                    chatPlaceholder: '質問を入力してください...',
                                                    chatGenerating: '回答を生成中です...',
                                                    chatError: 'サーバーとの通信中にエラーが発生しました。',
                                                    chatNoAnswer: '回答を取得できませんでした。',
                                                    chatWelcome: 'こんにちは！分析されたドキュメントの内容について質問してください。',
                                                    aiAnalyzing: '分析中...',
                                                    aiCompleted: 'AI分析が完了しました。注釈一覧を確認してください。',
                                                    noFile: 'まずPDFファイルをアップロードしてください。',
                                                    parsingError: 'AIレスポンスを解析できませんでした。',
                                                    existingLabel: '[既設]',
                                                    referenceLabel: '参照原文',
                                                    allPages: '全ページ',
                                                    pageTemplate: '{current} / {total} ページ',
                                                    noExport: '書き出し可能な注釈がありません。',
                                                    enterComment: '注釈の内容を入力してください。',
                                                    enterKeyword: '検索キーワードを入力してください。',
                                                    selectArea: 'PDFビューアーでマウスをドラッグして領域を選択してください。',
                                                    loadingLib: 'PDFライブラリをロード中です。しばらくしてから再試行してください。',
                                                    loadFileFail: 'ファイルの読み込みに失敗しました。',
                                                    onlyPdf: 'PDFファイルのみアップロード可能です。'
                                                },"""

# Regex to find ko: { ... } and ja: { ... } and replace them
content = re.sub(r'ko:\s*\{.*?\},', ko_translations, content, flags=re.DOTALL)
content = re.sub(r'ja:\s*\{.*?\},', ja_translations, content, flags=re.DOTALL)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully restored characters in pdf_comment_workspace.html")
