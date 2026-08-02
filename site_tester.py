import time
import os
from datetime import datetime
from playwright.sync_api import sync_playwright

SITE_URL = "https://aitrader-87e9v7yaqcv7ahkzkljjq.streamlit.app"
LOG_FILE = "site_test_errors.log"
SCREENSHOT_DIR = "test_screenshots"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def log_event(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")

def log_issue(issue_type, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [{issue_type}] {message}\n"
    print(f"FAIL: {entry.strip()}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)

def run_automated_test():
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_event("Starting new test pass...")
    issues_found = []

    with sync_playwright() as p:
        log_event("Launching headless Chromium browser instance...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()

        page.on("console", lambda msg: issues_found.append(f"Console {msg.type.upper()}: {msg.text}") if msg.type in ["error"] else None)
        page.on("requestfailed", lambda req: issues_found.append(f"Network Failure: {req.url} - {req.failure}"))

        try:
            log_event(f"Navigating to live app URL: {SITE_URL}")
            start_time = time.time()
            response = page.goto(SITE_URL, wait_until="networkidle", timeout=45000)
            elapsed = round(time.time() - start_time, 2)
            log_event(f"Page responded in {elapsed}s (HTTP Status: {response.status if response else 'None'})")

            if not response or response.status >= 400:
                issues_found.append(f"HTTP Status Error: {response.status if response else 'No Response'}")

            log_event("Waiting for Streamlit app container (.main) to render...")
            page.wait_for_selector(".main", timeout=30000)
            log_event("App container mounted! Pausing 3s for scripts to stabilize...")
            time.sleep(3)

            log_event("Scanning DOM content for unescaped raw HTML leaks...")
            page_html = page.content()
            if '<div style="' in page_html and '<span style="' in page_html and 'display: inline-block' in page_html:
                issues_found.append("UI Anomaly: Unescaped raw HTML string rendering visible on screen!")
                log_event("WARNING: Raw HTML leak detected on screen!")

            tabs = ["Performance & Active Positions", "Engine Scan Status & Logs", "Detailed AI Brain Analysis"]
            for idx, tab_name in enumerate(tabs, 1):
                log_event(f"Testing Tab [{idx}/3]: '{tab_name}'...")
                try:
                    tab_element = page.get_by_role("tab", name=tab_name)
                    if tab_element.is_visible():
                        tab_element.click()
                        log_event(f"Clicked tab '{tab_name}' - waiting 1.5s...")
                        time.sleep(1.5)
                    else:
                        log_event(f"WARNING: Tab element '{tab_name}' not visible!")
                        issues_found.append(f"UI Missing: Could not locate tab '{tab_name}'")
                except Exception as tab_err:
                    log_event(f"WARNING: Exception clicking tab '{tab_name}'")
                    issues_found.append(f"Tab Click Error ('{tab_name}'): {tab_err}")

            if issues_found:
                screenshot_path = os.path.join(SCREENSHOT_DIR, f"error_{timestamp_str}.png")
                log_event(f"Saving error screenshot to {screenshot_path}...")
                page.screenshot(path=screenshot_path, full_page=True)
                for issue in issues_found:
                    log_issue("FAIL", f"{issue} | Screenshot: {screenshot_path}")
            else:
                log_event("SUCCESS: Site check complete! No errors or anomalies detected.")

        except Exception as crash_err:
            screenshot_path = os.path.join(SCREENSHOT_DIR, f"crash_{timestamp_str}.png")
            log_event(f"CRASH DETECTED: {crash_err}")
            try:
                page.screenshot(path=screenshot_path, full_page=True)
                log_event(f"Crash screenshot saved to {screenshot_path}")
            except Exception:
                pass
            log_issue("CRASH", f"Test runner exception: {crash_err} | Screenshot: {screenshot_path}")

        finally:
            log_event("Closing browser context...")
            browser.close()
            log_event("Browser closed cleanly.")

if __name__ == "__main__":
    run_automated_test()
