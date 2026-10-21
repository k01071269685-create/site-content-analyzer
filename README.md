# 통합 사이트·이미지 분석기

입력한 사이트 한 곳의 같은 도메인 공개 HTML 페이지를 최대 40개까지 탐색하고 다음을 결합합니다.
- K-pop 여성 아이돌/그룹 이름 사전 + 사용자 지정 키워드 탐지
- 제목/본문/이미지 alt/파일명 검색
- OCR을 이용한 이미지 내부 글자 추출
- 선택적 AI 이미지 맥락 분석(공연, 화보, 공항/공개 행사, 단체 사진 등 일반적 유형)
- 통합 관련성 점수와 최신순 정렬
- 원문 게시물 링크 및 이미지 미리보기

## 실행
Python 3.10 이상 권장

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
브라우저에서 http://127.0.0.1:5000 을 엽니다.

## OCR 설치
`pytesseract`는 Python 래퍼이므로 Tesseract OCR 엔진을 별도로 설치해야 합니다. 한국어 OCR에는 `kor` 언어 데이터가 필요합니다. 설치하지 못하면 OCR 단계는 실패하거나 영어만 시도합니다.

## AI 이미지 분석 설정
AI 이미지 분석은 OpenAI API를 사용하도록 구현되어 있습니다. `OPENAI_API_KEY` 환경 변수를 설정하고, 필요하면 `OPENAI_VISION_MODEL`로 사용할 수 있는 이미지 입력 모델을 지정하세요. API 사용에는 별도의 계정/API 비용이 발생할 수 있습니다. API 키를 코드에 직접 넣거나 공개 저장소에 올리지 마세요.

Windows PowerShell 예:
```powershell
$env:OPENAI_API_KEY="여기에_API_키"
python app.py
```

macOS/Linux:
```bash
export OPENAI_API_KEY="여기에_API_키"
python app.py
```

## 분석 점수
기본 점수는 텍스트 키워드 일치(45%), 이미지 alt/파일명/OCR 일치(20%), AI가 평가한 K-pop 엔터테인먼트 맥락 관련성(35%)을 결합합니다. AI 점수는 일반적 시각 맥락의 추정치이며 인물의 신원을 확인하거나 증명하지 않습니다. AI를 비활성화하거나 API 키가 없으면 해당 항목은 0으로 처리됩니다. 실제 운영 데이터에 맞춰 가중치를 조정하세요.

## 중요 제한 및 안전
- 사진 속 얼굴로 특정 아이돌의 신원을 식별하거나 검증하지 않습니다. AI는 이미지의 일반적인 유형과 맥락만 분석합니다.
- 이미지 속 글자를 OCR로 추출할 수 있지만, 해상도·글꼴·언어 데이터에 따라 오류가 발생합니다.
- Google 검색 결과를 직접 수집하지 않습니다. 입력한 사이트 내부 링크만 분석합니다.
- JavaScript 렌더링, 로그인 전용, 차단된 페이지는 수집되지 않을 수 있습니다.
- 사이트 이용약관과 robots.txt를 확인하고 허용된 범위에서만 사용하세요.
- 외부 배포 전 SSRF 방지, robots.txt 확인, 도메인/리다이렉트 검증, 요청 제한, 캐시, 파일 크기 제한, 비밀 키 관리, 운영용 서버 설정이 필요합니다.
- `debug=True`는 로컬 개발용입니다. 공개 배포 전 비활성화하세요.
