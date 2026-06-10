# tools/page_scanner.py
import json
import logging
import subprocess
import sys
from datetime import datetime
from graph.state import PageScanResult

logger = logging.getLogger(__name__)


def scan_page(base_url: str, url_path: str, feature_module: str) -> PageScanResult:
    """
    Scans a live web page using Playwright in a subprocess.
    Subprocess avoids conflict with Streamlit's event loop.
    """
    full_url = f"{base_url.rstrip('/')}{url_path}"
    logger.info(f"Scanning page: {full_url}")

    scanner_script = f"""
import json
from playwright.sync_api import sync_playwright
elements = []
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("{full_url}", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        for level in ["h1","h2","h3","h4"]:
            for h in page.locator(level).all():
                try:
                    text = h.inner_text().strip()
                    if text:
                        elements.append({{"element_type":"heading","locator":level,"text":text,"attributes":{{"level":level}}}})
                except: pass

        for inp in page.locator("input").all():
            try:
                attrs = {{
                    "type": inp.get_attribute("type") or "text",
                    "id":   inp.get_attribute("id") or "",
                    "name": inp.get_attribute("name") or "",
                    "placeholder": inp.get_attribute("placeholder") or ""
                }}
                if attrs["id"]:
                    lid = "#" + attrs["id"]
                elif attrs["name"]:
                    lid = "input[name='" + attrs["name"] + "']"
                else:
                    lid = "input"
                etype = "checkbox" if attrs["type"] == "checkbox" else "input"
                elements.append({{"element_type":etype,"locator":lid,"text":attrs["placeholder"],"attributes":attrs}})
            except: pass

        for btn in page.locator("button").all():
            try:
                text  = btn.inner_text().strip()
                btype = btn.get_attribute("type") or "button"
                bid   = btn.get_attribute("id") or ""
                lid   = ("#" + bid) if bid else ("button[type='" + btype + "']")
                elements.append({{"element_type":"button","locator":lid,"text":text,"attributes":{{"type":btype,"id":bid}}}})
            except: pass

        for sel in page.locator("select").all():
            try:
                sid  = sel.get_attribute("id") or ""
                sname= sel.get_attribute("name") or ""
                if sid:
                    lid = "#" + sid
                elif sname:
                    lid = "select[name='" + sname + "']"
                else:
                    lid = "select"
                elements.append({{"element_type":"dropdown","locator":lid,"text":"","attributes":{{"id":sid,"name":sname}}}})
            except: pass

        for a in page.locator("a").all():
            try:
                text = a.inner_text().strip()
                href = a.get_attribute("href") or ""
                if text:
                    elements.append({{"element_type":"link","locator":"a:has-text('" + text + "')","text":text,"attributes":{{"href":href}}}})
            except: pass

        browser.close()
except Exception as ex:
    pass

print(json.dumps(elements))
"""

    elements = []
    try:
        result = subprocess.run(
            [sys.executable, "-c", scanner_script],
            capture_output = True,
            text           = True,
            timeout        = 60
        )
        if result.returncode == 0 and result.stdout.strip():
            elements = json.loads(result.stdout.strip())
            logger.info(
                f"Scan complete for {feature_module}: "
                f"found {len(elements)} elements"
            )
        else:
            logger.warning(
                f"Scanner returned no data for {full_url}. "
                f"stderr: {result.stderr[:200]}"
            )
    except Exception as e:
        logger.error(f"Error scanning {full_url}: {e}")

    return {
        "url"            : full_url,
        "feature_module" : feature_module,
        "elements"       : elements,
        "scan_timestamp" : datetime.now().isoformat(),
    }


def format_scan_for_llm(scan_result: PageScanResult) -> str:
    """
    Formats page scan result as clean text for LLM prompt.
    """
    if not scan_result:
        return "No page scan data available."

    lines = [
        f"Page URL: {scan_result['url']}",
        f"Scanned at: {scan_result['scan_timestamp']}",
        "",
        "Elements found on page:",
        "─" * 40,
    ]

    by_type = {}
    for el in scan_result["elements"]:
        etype = el["element_type"]
        if etype not in by_type:
            by_type[etype] = []
        by_type[etype].append(el)

    for etype, els in by_type.items():
        lines.append(f"\n{etype.upper()}S ({len(els)} found):")
        for el in els:
            lines.append(f"  Locator : {el['locator']}")
            if el.get("text"):
                lines.append(f"  Text    : {el['text']}")
            lines.append("")

    return "\n".join(lines)
