"""
Test de l'extraction de dates améliorée.
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from playwright.async_api import async_playwright

from pipeline_ingestion_blogs.article_scraper import (
    extract_date,
    extract_date_from_metadata,
    DEFAULT_JS_SCRIPT
)

async def test_date_extraction():
    """Teste l'extraction de dates sur quelques URLs."""

    print("\n" + "="*70)
    print("TEST D'EXTRACTION DE DATES")
    print("="*70 + "\n")

    test_urls = [
        "https://www.cabinetaci.com/le-procureur-de-la-republique-definition-statut-role/",
        "https://www.cabinetaci.com/la-delegation-de-pouvoirs/",
        "https://www.lekbinet.com/feminicide/grenoble"
    ]

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(args=['--no-sandbox'])
    context = await browser.new_context()

    crawler = AsyncWebCrawler()
    crawler.browser = browser
    crawler.context = context

    session = aiohttp.ClientSession()

    try:
        for url in test_urls:
            print(f"URL: {url}")

            try:
                run_config = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    js_code=[DEFAULT_JS_SCRIPT],
                    wait_until='networkidle'
                )

                result = await crawler.arun(url=url, config=run_config)

                if result and result.html:
                    soup = BeautifulSoup(result.html, "lxml")
                    text_content = soup.get_text(separator=" ", strip=True)

                    # Tester métadonnées
                    date_meta = extract_date_from_metadata(soup)
                    print(f"  Date (métadonnées): {date_meta if date_meta else 'Non trouvée'}")

                    # Tester extraction complète
                    date_full = extract_date(text_content, soup)
                    print(f"  Date (extraction complète): {date_full if date_full else 'Non trouvée'}")

                    # Afficher quelques meta tags trouvés
                    meta_published = soup.find('meta', {'property': 'article:published_time'})
                    if meta_published:
                        print(f"  Meta article:published_time: {meta_published.get('content')}")

                    time_elem = soup.find('time', {'datetime': True})
                    if time_elem:
                        print(f"  Time datetime: {time_elem.get('datetime')}")

                    print()

            except Exception as e:
                print(f"  Erreur: {str(e)[:100]}\n")

    finally:
        await session.close()
        await context.close()
        await browser.close()
        await playwright.stop()

    print("="*70 + "\n")

if __name__ == "__main__":
    asyncio.run(test_date_extraction())
