import sys
import os
import asyncio
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from core.config_loader import _load_env
_load_env()

from shared.browser_manager import BrowserManager, get_naver_page

async def debug_html():
    manager = BrowserManager()
    try:
        page = await get_naver_page(manager)
        url = "https://cafe.naver.com/ca-fe/cafes/26347614/menus/23?viewType=L"
        print(f"Navigating to {url}...")
        await page.goto(url)
        await asyncio.sleep(5) # Wait for SPA
        
        # Check if content is loaded
        content = await page.content()
        with open("scratch/naver_debug.html", "w") as f:
            f.write(content)
        print(f"HTML saved to scratch/naver_debug.html. Total length: {len(content)}")
        
        # Try to find links
        links = await page.query_selector_all("a")
        print(f"Found {len(links)} links on page.")
        
        article_links = [l for l in links if "/articles/" in (await l.get_attribute("href") or "")]
        print(f"Found {len(article_links)} links containing '/articles/'.")
        
    finally:
        await manager.close()

if __name__ == "__main__":
    asyncio.run(debug_html())
