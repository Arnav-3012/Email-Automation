"""Grafana panel screenshot taker — Chrome Selenium → Edge Selenium → mss fallback."""

import subprocess
import time
from io import BytesIO

from PIL import Image, ImageDraw


# ---------------------------------------------------------------------------
# Placeholder image
# ---------------------------------------------------------------------------

def _unavailable_png_bytes(width: int = 1000, height: int = 500) -> bytes:
    """Return a plain white PNG with centred 'Panel unavailable' text."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((width // 2, height // 2), "Panel unavailable", fill=(180, 180, 180), anchor="mm")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _unavailable_png() -> list[bytes]:
    """Return the placeholder as a single-element list for consistency with screenshot returns."""
    return [_unavailable_png_bytes()]


# ---------------------------------------------------------------------------
# Browser drivers
# ---------------------------------------------------------------------------

def _get_chrome_driver():
    """Return a headless Chrome WebDriver."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,800")
    opts.add_argument("--disable-extensions")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)


def _get_edge_driver():
    """Return a headless Edge WebDriver, with fallback for older selenium."""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,800")
    opts.add_argument("--inprivate")
    try:
        from selenium.webdriver.edge.service import Service
        from webdriver_manager.microsoft import EdgeChromiumDriverManager
        service = Service(EdgeChromiumDriverManager().install())
        return webdriver.Edge(service=service, options=opts)
    except Exception:
        return webdriver.Edge(options=opts)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def _login(driver, base_url: str, username: str, password: str) -> None:
    """Log in to Grafana via the /login page."""
    driver.get(f"{base_url}/login")
    time.sleep(3)
    try:
        from selenium.webdriver.common.by import By
        driver.find_element(By.NAME, "user").send_keys(username)
        driver.find_element(By.NAME, "password").send_keys(password)
        driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        time.sleep(3)
    except Exception as e:
        print(f"[screenshot_taker] Login error: {e}", flush=True)


# ---------------------------------------------------------------------------
# Screenshot helpers
# ---------------------------------------------------------------------------

def _selenium_screenshot(driver, base_url: str, dashboard_uid: str, panel_id: int, org_id: int = 1) -> list[bytes]:
    """Navigate to the panel URL and return PNG chunks as a list of bytes.

    Resizes the window to the full page height so tall panels are captured
    completely. Returns a list with one element for panels up to 2000 px tall,
    or multiple 2000-px chunks for taller panels.
    """
    url = (
        f"{base_url}/d-solo/{dashboard_uid}"
        f"?orgId={org_id}&panelId={panel_id}&kiosk&theme=light&from=now-6h&to=now"
    )
    driver.set_window_size(1280, 800)
    driver.get(url)
    time.sleep(5)

    # Expand window to full content size so nothing is clipped
    total_height = driver.execute_script("return document.body.scrollHeight")
    total_width = driver.execute_script("return document.body.scrollWidth")
    driver.set_window_size(max(1280, total_width), max(800, min(total_height, 8000)))
    time.sleep(1)

    png_bytes = driver.get_screenshot_as_png()

    img = Image.open(BytesIO(png_bytes))
    width, height = img.size

    if height <= 2000:
        return [png_bytes]

    # Split tall images into 2000-px chunks
    chunks: list[bytes] = []
    y = 0
    while y < height:
        chunk = img.crop((0, y, width, min(y + 2000, height)))
        buf = BytesIO()
        chunk.save(buf, format="PNG")
        chunks.append(buf.getvalue())
        y += 2000
    return chunks


def _mss_screenshot(base_url: str, dashboard_uid: str, panel_id: int, org_id: int = 1) -> list[bytes]:
    """Open the panel URL in the default browser and capture the full screen with mss."""
    import mss

    url = (
        f"{base_url}/d-solo/{dashboard_uid}"
        f"?orgId={org_id}&panelId={panel_id}&kiosk&theme=light&from=now-6h&to=now"
    )
    subprocess.Popen(["cmd", "/c", "start", url])
    time.sleep(8)
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    img = img.resize((1000, 500), Image.LANCZOS)
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return [buf.getvalue()]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capture_full_dashboard(dashboard_uid: str, grafana_settings: dict) -> bytes:
    """Capture a full-height screenshot of a Grafana dashboard in kiosk mode.

    Scrolls through the page first so lazy-loaded panels render, then expands
    the browser window to the full scrollHeight before taking the final shot.
    """
    base_url = grafana_settings.get("url", "").rstrip("/")
    username = grafana_settings.get("username", "")
    password = grafana_settings.get("password", "")

    driver = None
    try:
        driver = _get_chrome_driver()
        _login(driver, base_url, username, password)
    except Exception:
        try:
            if driver:
                driver.quit()
            driver = _get_edge_driver()
            _login(driver, base_url, username, password)
        except Exception as e:
            print(f"[screenshot_taker] Full dashboard capture failed: {e}", flush=True)
            return _unavailable_png_bytes()

    try:
        org_id = grafana_settings.get("org_id", 1)
        url = f"{base_url}/d/{dashboard_uid}?orgId={org_id}&kiosk&theme=light&from=now-6h&to=now"
        driver.set_window_size(1920, 1080)
        driver.get(url)
        time.sleep(5)  # wait for initial panel render

        # Scroll through the page so every panel (including lazy-loaded ones) renders
        viewport_h: int = driver.execute_script("return window.innerHeight")
        scroll_y = 0
        while True:
            total_h = driver.execute_script("return document.body.scrollHeight")
            if scroll_y >= total_h:
                break
            driver.execute_script(f"window.scrollTo(0, {scroll_y})")
            time.sleep(0.4)
            scroll_y += viewport_h

        # Re-measure after scrolling (lazy content may have extended the page)
        total_h = driver.execute_script("return document.body.scrollHeight")
        total_w = driver.execute_script("return document.body.scrollWidth")

        # Expand window to the full content size for a single-shot capture
        driver.set_window_size(max(1920, total_w), max(1080, min(total_h, 12000)))
        time.sleep(3)  # allow re-render at new viewport size

        driver.execute_script("window.scrollTo(0, 0)")
        time.sleep(0.5)
        return driver.get_screenshot_as_png()

    except Exception as e:
        print(f"[screenshot_taker] Full dashboard screenshot failed: {e}", flush=True)
        return _unavailable_png_bytes()
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def capture_panels(dashboard_uid: str, panel_ids: list, grafana_settings: dict) -> dict[int, list[bytes]]:
    """Screenshot every panel, trying Chrome → Edge → mss in order.

    Returns a panel_id → list[bytes] dict. Each list contains one PNG per
    vertical chunk (tall panels are split into 2000-px segments).
    Failed panels get a single-element placeholder list.
    """
    base_url = grafana_settings.get("url", "").rstrip("/")
    username = grafana_settings.get("username", "")
    password = grafana_settings.get("password", "")
    org_id = grafana_settings.get("org_id", 1)

    results: dict[int, list[bytes]] = {}
    driver = None
    method: str | None = None

    # Level 1 — Chrome Selenium
    try:
        print("[screenshot_taker] Trying Chrome Selenium...", flush=True)
        driver = _get_chrome_driver()
        _login(driver, base_url, username, password)
        method = "Chrome"
        print("[screenshot_taker] Chrome Selenium OK", flush=True)
    except Exception as e:
        print(f"[screenshot_taker] Chrome Selenium failed: {e}", flush=True)
        driver = None

    # Level 2 — Edge Selenium
    if driver is None:
        try:
            print("[screenshot_taker] Trying Edge Selenium...", flush=True)
            driver = _get_edge_driver()
            _login(driver, base_url, username, password)
            method = "Edge"
            print("[screenshot_taker] Edge Selenium OK", flush=True)
        except Exception as e:
            print(f"[screenshot_taker] Edge Selenium failed: {e}", flush=True)
            driver = None

    # Selenium path (Chrome or Edge)
    if driver is not None:
        try:
            for panel_id in panel_ids:
                try:
                    chunks = _selenium_screenshot(driver, base_url, dashboard_uid, panel_id, org_id)
                    results[panel_id] = chunks
                    print(f"[screenshot_taker] Panel {panel_id} captured via {method} ({len(chunks)} chunk(s))", flush=True)
                except Exception as e:
                    print(f"[screenshot_taker] Panel {panel_id} failed: {e}", flush=True)
                    results[panel_id] = _unavailable_png()
        finally:
            try:
                driver.quit()
            except Exception:
                pass
        return results

    # Level 3 — mss screen capture
    print("[screenshot_taker] Selenium blocked, trying mss screen capture...", flush=True)
    for panel_id in panel_ids:
        try:
            chunks = _mss_screenshot(base_url, dashboard_uid, panel_id, org_id)
            results[panel_id] = chunks
            print(f"[screenshot_taker] Panel {panel_id} captured via mss", flush=True)
        except Exception as e:
            print(f"[screenshot_taker] Panel {panel_id} mss failed: {e}", flush=True)
            results[panel_id] = _unavailable_png()

    return results
