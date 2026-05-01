import sys
import os
import asyncio
import logging
from pathlib import Path

# 프로젝트 루트 경로 추가
sys.path.append(os.getcwd())

# .env 로드 (NexusConfig를 통해 로드하거나 직접 처리)
from core.config_loader import _load_env
_load_env()

print(f"DEBUG: NID_AUT exists: {bool(os.getenv('NID_AUT'))}")
print(f"DEBUG: NID_SES exists: {bool(os.getenv('NID_SES'))}")

from skills.naver_cafe_reader import run

# 로그 설정
logging.basicConfig(level=logging.INFO)

def test_board_posts():
    print("\n--- 4. 특정 게시판 '오늘 글만' 추출 테스트 ---")
    url = "https://cafe.naver.com/ca-fe/cafes/26347614/menus/23?viewType=L"
    params = {
        "action": "board",
        "url": url,
        "filter_today": False
    }
    result = run(params)
    print(f"조회된 오늘 글 수: {result.get('count', 0)}")
    for post in result.get("posts", []):
        print(f"- [{post['date']}] {post['title']} ({post['url']})")

if __name__ == "__main__":
    test_board_posts()
