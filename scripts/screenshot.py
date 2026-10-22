"""Capture the README screenshots from a running demo server.

    vc serve --demo --port 8000          # in one terminal
    pip install playwright
    python scripts/screenshot.py http://127.0.0.1:8000

Writes docs/screenshot.png (answer and runtime evidence) and
docs/screenshot-stages.png (first opinions and peer review). It drives the
locally installed Chrome (channel "chrome"), so no browser download is needed.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
DOCS = Path(__file__).resolve().parent.parent / "docs"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto(URL)
    # Demo mode pre-fills the sample question once /api/health has answered.
    page.wait_for_function("document.querySelector('.chat-textarea')?.value.length > 0")
    page.click(".send-btn")
    page.wait_for_selector(".result-answer", timeout=60_000)
    page.wait_for_timeout(500)
    DOCS.mkdir(exist_ok=True)
    page.screenshot(path=str(DOCS / "screenshot.png"))

    page.click(".stages-toggle")
    page.wait_for_selector(".stage-card")
    page.evaluate("document.querySelector('.stages-section').scrollIntoView()")
    page.wait_for_timeout(300)
    page.screenshot(path=str(DOCS / "screenshot-stages.png"))
    browser.close()

print(f"wrote {DOCS / 'screenshot.png'} and {DOCS / 'screenshot-stages.png'}")
