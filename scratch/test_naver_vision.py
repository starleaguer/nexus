import sys
import os
import asyncio
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from core.config_loader import _load_env
_load_env()

from skills.naver_cafe_reader import NaverCafeSkill

async def test_vision():
    print("\n--- 5. 네이버 카페 이미지 분석 테스트 ---")
    skill = NaverCafeSkill()
    
    # User provided URL: https://cafe.naver.com/f-e/cafes/26347614/articles/504967?menuid=86&referrerAllArticles=false
    params = {
        "action": "read",
        "cafe_id": "26347614",
        "article_id": "504967",
        "analyze_vision": True
    }
    
    result = await skill.run(params)
    print(f"상태: {result.get('status')}")
    if result.get("status") == "success":
        data = result.get("data", {})
        print(f"제목: {data.get('title')}")
        print(f"이미지 URL 수: {len(data.get('images', []))}")
        print(f"캡처된 이미지 경로: {data.get('image_paths', [])}")
        
        # If images are captured, show their paths
        for path in data.get("image_paths", []):
            print(f"✅ 이미지 저장됨: {path}")
    else:
        print(f"❌ 오류 발생: {result}")

if __name__ == "__main__":
    asyncio.run(test_vision())
