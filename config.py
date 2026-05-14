import os

# KIS API 설정 (환경변수에서 읽어옴)
APP_KEY    = os.environ["KIS_APP_KEY"]
APP_SECRET = os.environ["KIS_APP_SECRET"]
ACCT_STOCK = os.environ["KIS_ACCT_STOCK"]       # 국내주식 계좌번호
ACCT_OVRS  = os.environ.get("KIS_ACCT_OVRS", os.environ["KIS_ACCT_STOCK"])  # 해외주식 계좌번호 (없으면 국내와 동일)
HTS_ID     = os.environ["KIS_HTS_ID"]
IS_PAPER   = os.environ.get("KIS_IS_PAPER", "false").lower() == "true"
