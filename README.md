# 코인 투자 도우미

빗썸(이후 업비트)과 연동하는 한국어 비트코인·알트코인 투자 프로그램입니다.
기획서: https://claude.ai/artifact/AJRv9PBS134jSbLNFDgrJx

## 지금 들어 있는 것 (1단계)

- 빗썸 API 2.0 연동: 원화 마켓 목록, 현재가, 캔들(1분~월봉), 잔고 조회, 시장가 매수
- 주간 정기 매수 전략: 요일·시각(KST)·금액·코인·누적 한도 설정, 기본값 꺼짐, 모의투자/실거래 선택
- 목표 수익 매도: 매수·매도 수수료를 모두 빼고도 평균 단가보다 목표 % 이상 오르면 보유량 일부 매도
- 수익 분석 화면: 투자 원금, 평가 금액, 실현·미실현 손익, 수익률, 낸 수수료, 손익 흐름 차트, 거래 기록
- 매매 엔진: API 서버와 별도 프로세스로 실행, 같은 주에 두 번 매수하지 않음
- 한국어 웹 화면: 대시보드(관심 코인 시세, 캔들 차트), 자동매매 설정. 휴대폰 화면 대응

## 구조

```
backend/   Python FastAPI API 서버 + 매매 엔진
  app/exchanges/   거래소 어댑터 (공통 인터페이스 base.py, 빗썸 bithumb.py)
  app/strategies/  매매 전략 (주간 정기 매수 dca.py)
  app/engine.py    매매 엔진 (python -m app.engine)
  app/main.py      API 서버
frontend/  React + TypeScript 화면 (Vite)
```

## 윈도우 PC에서 실행

1. 파이썬 3.12 이상(설치 때 "Add python.exe to PATH" 체크), Node.js LTS, Git을 설치합니다.
2. `setup.bat`을 더블클릭합니다. 끝나면 `.env` 파일에 빗썸 API 키를 넣습니다.
3. `start.bat`을 더블클릭하면 API 서버, 매매 엔진, 화면이 켜지고 브라우저가 열립니다.

## 직접 실행 (맥, 리눅스)

```bash
# 1) 백엔드
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env   # 키를 넣고 환경 변수로 불러오기
uvicorn app.main:app --reload          # API 서버 (http://127.0.0.1:8000)
python -m app.engine                   # 매매 엔진 (다른 터미널)

# 2) 화면
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

## 테스트

```bash
cd backend && pytest
cd frontend && npm run build && npm run lint
```

## 안전 수칙

- API 키는 출금 권한 없이 발급하고, 빗썸에 서버 IP만 허용합니다.
- `.env`는 저장소에 올리지 않습니다.
- 실거래는 모의투자로 충분히 돌려 본 뒤 작은 금액으로 시작합니다.
- 빗썸 최소 주문 금액(5,000원)과 API 응답 형식은 공식 문서(https://apidocs.bithumb.com)로 다시 확인해야 합니다.
