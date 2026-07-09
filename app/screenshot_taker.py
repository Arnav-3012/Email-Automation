"""Grafana panel screenshot taker — Chrome Selenium → Edge Selenium → mss fallback."""

import logging
import platform
import subprocess
import time
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw

logger = logging.getLogger(__name__)

IS_LINUX = platform.system() == "Linux"


def _is_debug() -> bool:
    try:
        from app import config_manager
        return bool(config_manager.get_debug_mode())
    except Exception:
        return False


def _dbg(msg: str) -> None:
    if _is_debug():
        logger.debug(msg)
        print(f"[DEBUG] {msg}", flush=True)


def _warn(msg: str) -> None:
    """Print/log a warning regardless of debug mode — for conditions the operator should always see."""
    logger.warning(msg)
    print(f"[WARN] [screenshot_taker] {msg}", flush=True)


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
# Whitespace trimming
# ---------------------------------------------------------------------------

def _trim_whitespace(png_bytes: bytes, aggressive: bool = True, min_padding: int = 5) -> bytes:
    """Crop excess background border from a screenshot.

    Detects the background colour from a thin border sample on all four edges,
    then crops to the bounding box of everything that differs from it.

    Args:
        png_bytes: PNG image bytes.
        aggressive: True for individual panels (tighter crop); False for full
            dashboard overviews (preserve more padding around the layout).
        min_padding: Minimum pixels of padding kept around the detected content,
            to avoid clipping edge pixels.

    Returns:
        Trimmed PNG bytes, or the original bytes unchanged if trimming fails or
        would remove more than half the image in either dimension.
    """
    try:
        img = Image.open(BytesIO(png_bytes)).convert("RGB")
        original_size = img.size
        w, h = img.size
        border_width = 5

        # Sample a thin border on all four edges to find the background colour.
        edges = []
        edges.extend(img.getpixel((x, y)) for x in range(w) for y in range(border_width))
        edges.extend(img.getpixel((x, y)) for x in range(w) for y in range(max(0, h - border_width), h))
        edges.extend(img.getpixel((x, y)) for x in range(border_width) for y in range(h))
        edges.extend(img.getpixel((x, y)) for x in range(max(0, w - border_width), w) for y in range(h))
        bg_color = max(set(edges), key=edges.count) if edges else (255, 255, 255)

        bg = Image.new("RGB", img.size, bg_color)
        diff = ImageChops.difference(img, bg)
        bbox = diff.getbbox()
        if not bbox:
            return png_bytes

        left, top, right, bottom = bbox
        padding = max(min_padding, int((right - left) * (0.01 if aggressive else 0.03)))

        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(img.width, right + padding)
        bottom = min(img.height, bottom + padding)

        # Safety check: don't let an over-eager crop remove more than half the image.
        if (right - left) < original_size[0] * 0.5 or (bottom - top) < original_size[1] * 0.5:
            return png_bytes

        img = img.crop((left, top, right, bottom))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    except Exception as e:
        logging.warning(f"[screenshot_taker] Whitespace trim failed: {e}, returning original screenshot")
        return png_bytes


# ---------------------------------------------------------------------------
# Browser drivers
# ---------------------------------------------------------------------------

def _get_chrome_driver():
    """Return a Chrome WebDriver — headless on Linux, on-screen on Windows."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    if IS_LINUX:
        _dbg("_get_chrome_driver: Linux detected, adding headless flags")
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--no-xshm")
        opts.add_argument("--disable-software-rasterizer")
        opts.add_argument("--ignore-certificate-errors")
        opts.add_argument("--ignore-ssl-errors")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--force-device-scale-factor=1")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(90)
    driver.implicitly_wait(10)
    return driver


def _get_edge_driver():
    """Return an Edge WebDriver — headless on Linux, on-screen on Windows. Falls back for older selenium."""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options

    opts = Options()
    if IS_LINUX:
        _dbg("_get_edge_driver: Linux detected, adding headless flags")
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--inprivate")
    try:
        from selenium.webdriver.edge.service import Service
        from webdriver_manager.microsoft import EdgeChromiumDriverManager
        service = Service(EdgeChromiumDriverManager().install())
        driver = webdriver.Edge(service=service, options=opts)
    except Exception:
        driver = webdriver.Edge(options=opts)
    driver.set_page_load_timeout(90)
    driver.implicitly_wait(10)
    return driver


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def _login(driver, base_url: str, username: str, password: str) -> bool:
    """Log in to Grafana via the /login page.

    Returns True if login appears to have succeeded, False otherwise.
    """
    driver.get(f"{base_url}/login")
    time.sleep(3)
    try:
        from selenium.webdriver.common.by import By
        driver.find_element(By.NAME, "user").send_keys(username)
        driver.find_element(By.NAME, "password").send_keys(password)
        driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        time.sleep(5)

        current_url = driver.current_url
        if "login" in current_url.lower():
            _warn(
                "Grafana login failed - still on login page after submit. "
                "Check credentials in Settings."
            )
            return False

        _dbg(f"Grafana login successful, redirected to: {current_url}")
        return True
    except Exception as e:
        _warn(f"Grafana login error: {e}")
        return False


def _is_still_logged_in(driver) -> bool:
    """Check whether the Grafana session is still active (i.e. not sitting on /login)."""
    try:
        return "login" not in driver.current_url.lower()
    except Exception:
        return True


def _wait_for_panel_render(driver, timeout: int = 60) -> None:
    """Wait for a Grafana panel/dashboard to finish loading data.

    Runs several best-effort strategies in sequence (each individually
    tolerant of failure/timeout), then applies a fixed buffer since Grafana
    panels have been observed to take 10-20s to fully render.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    try:
        WebDriverWait(driver, min(30, timeout)).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception:
        pass

    try:
        WebDriverWait(driver, min(30, timeout)).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                "[class*='panel-content'], div.react-grid-layout, [class*='dashboard-container']",
            ))
        )
    except Exception:
        pass

    try:
        WebDriverWait(driver, timeout).until_not(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                "[class*='panel-loading'], [class*='loadingIndicator'], div.panel-loading",
            ))
        )
    except Exception:
        pass

    try:
        WebDriverWait(driver, min(30, timeout)).until(
            lambda d: d.execute_script(
                "return window.performance.getEntriesByType('resource')"
                ".filter(r => r.responseEnd === 0).length === 0"
            )
        )
    except Exception:
        pass

    # Fixed buffer - dashboard panels take 10-20s; 25s covers render + animations.
    time.sleep(25)


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def _build_panel_url(
    base_url: str, dashboard_uid: str, panel_id: int, org_id: int,
    from_time: str, to_time: str, variables: dict = None,
) -> str:
    """Build a /d-solo panel screenshot URL including time range and template variables.

    Safe no-op for the variables part if `variables` is None/empty — matches
    the previous URL shape exactly for dashboards without template variables.
    """
    url = (
        f"{base_url}/d-solo/{dashboard_uid}"
        f"?orgId={org_id}&panelId={panel_id}&kiosk&theme=light&from={from_time}&to={to_time}"
    )
    if variables:
        for var_name, var_value in variables.items():
            url += f"&var-{var_name}={var_value}"
    return url


def _build_dashboard_url(
    base_url: str, dashboard_uid: str, org_id: int,
    from_time: str, to_time: str, variables: dict = None,
) -> str:
    """Build a /d full-dashboard screenshot URL including time range and template variables."""
    url = (
        f"{base_url}/d/{dashboard_uid}"
        f"?orgId={org_id}&kiosk=tv&theme=light&from={from_time}&to={to_time}"
    )
    if variables:
        for var_name, var_value in variables.items():
            url += f"&var-{var_name}={var_value}"
    return url


# ---------------------------------------------------------------------------
# Screenshot helpers
# ---------------------------------------------------------------------------

def _selenium_screenshot(
    driver, base_url: str, dashboard_uid: str, panel_id: int, org_id: int = 1,
    from_time: str = "now-24h", to_time: str = "now", variables: dict = None,
) -> list[bytes]:
    """Navigate to the panel URL and return PNG chunks as a list of bytes.

    Resizes the window to the full page height so tall panels are captured
    completely. Returns a list with one element for panels up to 2000 px tall,
    or multiple 2000-px chunks for taller panels.
    """
    url = _build_panel_url(base_url, dashboard_uid, panel_id, org_id, from_time, to_time, variables)
    _dbg(f"Panel URL: {url}")
    driver.set_window_size(1280, 800)
    driver.get(url)
    _wait_for_panel_render(driver)

    # Expand window to full content size so nothing is clipped
    total_height = driver.execute_script("return document.body.scrollHeight")
    total_width = driver.execute_script("return document.body.scrollWidth")
    driver.set_window_size(max(1280, total_width), max(800, min(total_height, 8000)))
    time.sleep(1)

    png_bytes = driver.get_screenshot_as_png()

    img = Image.open(BytesIO(png_bytes))
    width, height = img.size

    if height <= 2000:
        return [_trim_whitespace(png_bytes, aggressive=True, min_padding=5)]

    # Split tall images into 2000-px chunks
    chunks: list[bytes] = []
    y = 0
    while y < height:
        chunk = img.crop((0, y, width, min(y + 2000, height)))
        buf = BytesIO()
        chunk.save(buf, format="PNG")
        chunks.append(buf.getvalue())
        y += 2000
    return [_trim_whitespace(chunk, aggressive=True, min_padding=5) for chunk in chunks]


def _mss_screenshot(
    base_url: str, dashboard_uid: str, panel_id: int, org_id: int = 1,
    from_time: str = "now-24h", to_time: str = "now", variables: dict = None,
) -> list[bytes]:
    """Open the panel URL in the default browser and capture the full screen with mss."""
    import mss

    url = _build_panel_url(base_url, dashboard_uid, panel_id, org_id, from_time, to_time, variables)
    _dbg(f"Panel URL: {url}")
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
    png_bytes = _trim_whitespace(buf.getvalue(), aggressive=True, min_padding=5)
    return [png_bytes]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capture_full_dashboard(
    dashboard_uid: str, grafana_settings: dict,
    from_time: str = "now-24h", to_time: str = "now", variables: dict = None,
) -> bytes:
    """Capture a full-height screenshot of a Grafana dashboard in kiosk mode.

    Scrolls through the page first so lazy-loaded panels render, then expands
    the browser window to the full scrollHeight before taking the final shot.
    """
    base_url = grafana_settings.get("url", "").rstrip("/")
    username = grafana_settings.get("username", "")
    password = grafana_settings.get("password", "")

    driver = None
    login_ok = False
    try:
        driver = _get_chrome_driver()
        login_ok = _login(driver, base_url, username, password)
    except Exception:
        try:
            if driver:
                driver.quit()
            driver = _get_edge_driver()
            login_ok = _login(driver, base_url, username, password)
        except Exception as e:
            print(f"[screenshot_taker] Full dashboard capture failed: {e}", flush=True)
            return _unavailable_png_bytes()

    if not login_ok:
        _warn(
            "Grafana login failed for full dashboard capture - screenshot may "
            "show no data or the login page. Verify Grafana credentials in Settings."
        )

    try:
        org_id = grafana_settings.get("org_id", 1)
        url = _build_dashboard_url(base_url, dashboard_uid, org_id, from_time, to_time, variables)
        _dbg(f"Dashboard URL: {url}")
        driver.set_window_size(1920, 1080)
        driver.get(url)
        _wait_for_panel_render(driver, timeout=90)
        time.sleep(10)  # full dashboard has more panels, extra render buffer

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
        full_dashboard_bytes = driver.get_screenshot_as_png()
        return _trim_whitespace(full_dashboard_bytes, aggressive=False, min_padding=10)

    except Exception as e:
        print(f"[screenshot_taker] Full dashboard screenshot failed: {e}", flush=True)
        return _unavailable_png_bytes()
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def capture_panels(
    dashboard_uid: str, panel_ids: list, grafana_settings: dict,
    from_time: str = "now-24h", to_time: str = "now", variables: dict = None,
) -> dict[int, list[bytes]]:
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
    login_ok = False

    _dbg(f"capture_panels: OS detected={platform.system()} (IS_LINUX={IS_LINUX})")
    _dbg(f"capture_panels: variables={variables or {}}")

    # Level 1 — Chrome Selenium
    try:
        print("[screenshot_taker] Trying Chrome Selenium...", flush=True)
        _dbg(f"capture_panels: attempting Chrome Selenium for dashboard={dashboard_uid} panels={panel_ids} org_id={org_id}")
        driver = _get_chrome_driver()
        login_ok = _login(driver, base_url, username, password)
        method = "Chrome"
        print("[screenshot_taker] Chrome Selenium OK", flush=True)
        _dbg("capture_panels: Chrome Selenium driver ready")
    except Exception as e:
        print(f"[screenshot_taker] Chrome Selenium failed: {e}", flush=True)
        _dbg(f"capture_panels: Chrome Selenium failed ({e}), will try Edge")
        driver = None

    # Level 2 — Edge Selenium
    if driver is None:
        try:
            print("[screenshot_taker] Trying Edge Selenium...", flush=True)
            _dbg("capture_panels: attempting Edge Selenium")
            driver = _get_edge_driver()
            login_ok = _login(driver, base_url, username, password)
            method = "Edge"
            print("[screenshot_taker] Edge Selenium OK", flush=True)
            _dbg("capture_panels: Edge Selenium driver ready")
        except Exception as e:
            print(f"[screenshot_taker] Edge Selenium failed: {e}", flush=True)
            _dbg(f"capture_panels: Edge Selenium failed ({e}), will try mss")
            driver = None

    # Selenium path (Chrome or Edge)
    if driver is not None:
        if not login_ok:
            _warn(
                f"Grafana login failed via {method} - panel screenshots may show "
                "no data or the login page. Verify Grafana credentials in Settings."
            )
        try:
            for panel_id in panel_ids:
                if not _is_still_logged_in(driver):
                    _warn(f"Grafana session lost mid-job before panel {panel_id}, re-logging in")
                    login_ok = _login(driver, base_url, username, password)
                    if not login_ok:
                        _warn(f"Re-login failed before panel {panel_id}")

                for attempt in range(2):
                    try:
                        _dbg(f"capture_panels: screenshotting panel_id={panel_id} via {method} (attempt {attempt + 1})")
                        chunks = _selenium_screenshot(
                            driver, base_url, dashboard_uid, panel_id, org_id, from_time, to_time, variables
                        )
                        results[panel_id] = chunks
                        print(f"[screenshot_taker] Panel {panel_id} captured via {method} ({len(chunks)} chunk(s))", flush=True)
                        _dbg(f"capture_panels: panel_id={panel_id} OK — {len(chunks)} chunk(s)")
                        break
                    except Exception as e:
                        if attempt == 0:
                            _warn(f"Panel {panel_id} attempt 1 failed via {method}: {e}. Retrying...")
                            time.sleep(5)
                        else:
                            print(f"[screenshot_taker] Panel {panel_id} failed: {e}", flush=True)
                            _dbg(f"capture_panels: panel_id={panel_id} failed via {method}: {e} — using placeholder")
                            results[panel_id] = _unavailable_png()
        finally:
            try:
                driver.quit()
            except Exception:
                pass
        return results

    # Level 3 — mss screen capture (requires a real display, unavailable on headless Linux)
    if not IS_LINUX:
        print("[screenshot_taker] Selenium blocked, trying mss screen capture...", flush=True)
        _dbg("capture_panels: falling back to mss screen capture (Selenium unavailable)")
        for panel_id in panel_ids:
            for attempt in range(2):
                try:
                    _dbg(f"capture_panels: mss capturing panel_id={panel_id} (attempt {attempt + 1})")
                    chunks = _mss_screenshot(base_url, dashboard_uid, panel_id, org_id, from_time, to_time, variables)
                    results[panel_id] = chunks
                    print(f"[screenshot_taker] Panel {panel_id} captured via mss", flush=True)
                    _dbg(f"capture_panels: panel_id={panel_id} OK via mss")
                    break
                except Exception as e:
                    if attempt == 0:
                        _warn(f"Panel {panel_id} mss attempt 1 failed: {e}. Retrying...")
                        time.sleep(5)
                    else:
                        print(f"[screenshot_taker] Panel {panel_id} mss failed: {e}", flush=True)
                        _dbg(f"capture_panels: panel_id={panel_id} mss failed: {e} — using placeholder")
                        results[panel_id] = _unavailable_png()
    else:
        print("[screenshot_taker] Selenium blocked and running on Linux — mss not available on headless Linux, Chrome headless is required", flush=True)
        _dbg("capture_panels: mss not available on headless Linux, Chrome headless is required")
        for panel_id in panel_ids:
            results[panel_id] = _unavailable_png()

    return results
