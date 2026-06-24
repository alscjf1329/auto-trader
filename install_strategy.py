#!/usr/bin/env python3
"""마켓플레이스에서 전략을 다운로드해 strategies/ 에 설치합니다.

사용법:
  python install_strategy.py <전략ID>
  python install_strategy.py <전략ID> --endpoint https://your-profit-board.com
"""
import sys
import os
import re
import json
import urllib.request


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    strategy_id = sys.argv[1]

    # --endpoint 플래그 또는 .env / VERIFY_ENDPOINT 환경변수
    endpoint = None
    args = sys.argv[2:]
    for i, a in enumerate(args):
        if a == "--endpoint" and i + 1 < len(args):
            endpoint = args[i + 1]

    if not endpoint:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        endpoint = os.getenv("VERIFY_ENDPOINT")

    if not endpoint:
        print("엔드포인트를 지정하세요:")
        print("  python install_strategy.py <ID> --endpoint https://your-profit-board.com")
        print("  또는 .env 에 VERIFY_ENDPOINT=https://... 설정")
        sys.exit(1)

    endpoint = endpoint.rstrip("/")
    url = f"{endpoint}/api/marketplace/{strategy_id}"
    print(f"다운로드 중… {url}")

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.reason}")
        sys.exit(1)
    except Exception as e:
        print(f"오류: {e}")
        sys.exit(1)

    name = (data.get("name") or "").strip()
    code = data.get("code") or ""
    author = data.get("author") or "알 수 없음"
    desc = (data.get("description") or "")[:80]

    if not name or not code:
        print("응답 오류: name 또는 code 필드가 없습니다")
        sys.exit(1)

    fname = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_") or strategy_id[:12]
    dest_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategies")
    dest = os.path.join(dest_dir, f"{fname}.py")

    print(f"이름:   {name}")
    print(f"작성자: {author}")
    print(f"설명:   {desc}")
    print(f"저장위치: {dest}")

    if os.path.exists(dest):
        ans = input("\n파일이 이미 있습니다. 덮어쓸까요? [y/N] ").strip().lower()
        if ans != "y":
            print("취소됨")
            sys.exit(0)

    os.makedirs(dest_dir, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(code)

    # 다운로드 카운터 증가
    try:
        req = urllib.request.Request(
            f"{endpoint}/api/marketplace/{strategy_id}",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

    print(f"\n설치 완료!")
    print(f"settings.yaml 에 다음을 추가하세요:")
    print(f"\n  strategy:")
    print(f"    name: {fname}")


if __name__ == "__main__":
    main()
