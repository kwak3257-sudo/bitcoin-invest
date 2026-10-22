# 코인 투자 도우미

빗썸(이후 업비트)과 연동하는 한국어 비트코인·알트코인 투자 프로그램입니다.
기획서: https://claude.ai/artifact/AJRv9PBS134jSbLNFDgrJx

## 지금 들어 있는 것 (1단계)

- 빗썸 API 2.0 연동: 원화 마켓 목록, 현재가, 캔들(1분~월봉), 잔고 조회, 시장가 매수
- 주간 정기 매수 전략: 요일·시각(KST)·금액·코인·누적 한도 설정, 기본값 꺼짐, 모의투자/실거래 선택
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

## 실행 방법

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
