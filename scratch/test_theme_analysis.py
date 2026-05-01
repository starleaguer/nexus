import sys
import os
import asyncio
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from core.config_loader import _load_env
_load_env()

from skills.naver_cafe_reader import NaverCafeSkill

async def test_theme_analysis():
    print("\n--- 6. 국내 테마주 종합 분석 테스트 ---")
    skill = NaverCafeSkill()
    
    params = {
        "action": "theme_analysis"
    }
    
    result = await skill.run(params)
    print(f"상태: {result.get('status')}")
    
    if result.get("status") == "success":
        data = result.get("data", {})
        
        print(f"\n[핵심 뉴스 수집 결과 ({len(data['key_news'])}건)]")
        for news in data["key_news"]:
            print(f"- 제목: {news['title']}")
            print(f"  외부 기사 수집: {len(news.get('external_news', []))}건")
            for ext in news.get("external_news", []):
                print(f"    🔗 {ext['url']} (본문: {len(ext['detail'])}자)")
        
        print(f"\n[오늘의 테마 수집 결과 ({len(data['themes'])}건)]")
        for theme in data["themes"]:
            print(f"- 제목: {theme['title']}")
            print(f"  캡처 이미지: {len(theme.get('image_paths', []))}건")
            for img in theme.get("image_paths", []):
                print(f"    🖼️ {img}")

if __name__ == "__main__":
    asyncio.run(test_theme_analysis())
