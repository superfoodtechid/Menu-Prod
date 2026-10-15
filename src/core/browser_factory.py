import os
import time
import socket
import asyncio
import platform
import subprocess
import shutil
import tempfile
import urllib.request
from contextlib import contextmanager, asynccontextmanager
from rich.console import Console

console = Console()

def is_arm_architecture() -> bool:
    """Detect if running on ARM architecture (Raspberry Pi / Apple Silicon / ARM64 Linux)."""
    arch = platform.machine().lower()
    has_system_chromium = os.path.exists("/usr/lib/chromium/chromium") or os.path.exists("/usr/bin/chromium")
    return "arm" in arch or "aarch64" in arch or has_system_chromium

def get_free_port() -> int:
    """Find a free TCP port for CDP remote debugging."""
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def kill_process_tree(proc):
    """Safely and forcibly terminate a subprocess and its child processes to prevent zombie Chromium instances."""
    if not proc:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
    except Exception as e:
        console.print(f"Note during Chromium subprocess termination: {e}")
    finally:
        if hasattr(proc, "_log_file") and proc._log_file:
            try:
                proc._log_file.close()
            except Exception:
                pass
        if hasattr(proc, "_user_data_dir") and proc._user_data_dir and os.path.exists(proc._user_data_dir):
            try:
                shutil.rmtree(proc._user_data_dir, ignore_errors=True)
            except Exception:
                pass

def _wait_for_cdp_ready(port: int, proc: subprocess.Popen, log_file, timeout: float = 30.0):
    start = time.time()
    while time.time() - start < timeout:
        if proc.poll() is not None:
            log_content = ""
            if log_file:
                try:
                    log_file.seek(0)
                    log_content = log_file.read()[-1000:]
                except Exception:
                    pass
            raise RuntimeError(f"Chromium process exited prematurely with code {proc.returncode}. Log:\n{log_content}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"Chromium did not start listening on CDP port {port} within {timeout} seconds.")

async def _async_wait_for_cdp_ready(port: int, proc: subprocess.Popen, log_file, timeout: float = 30.0):
    start = time.time()
    while time.time() - start < timeout:
        if proc.poll() is not None:
            log_content = ""
            if log_file:
                try:
                    log_file.seek(0)
                    log_content = log_file.read()[-1000:]
                except Exception:
                    pass
            raise RuntimeError(f"Chromium process exited prematurely with code {proc.returncode}. Log:\n{log_content}")
        try:
            s = socket.socket()
            s.settimeout(0.3)
            s.connect(('127.0.0.1', port))
            s.close()
            return True
        except Exception:
            pass
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Chromium did not start listening on CDP port {port} within {timeout} seconds.")

def cleanup_zombie_chromium():
    """Utility to clean up any orphaned or stale Chromium debugging processes."""
    try:
        subprocess.run(["pkill", "-f", "remote-debugging-port"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
"""

OPTIMIZED_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--mute-audio",
    "--disable-background-networking",
    "--renderer-process-limit=2",
]

LEAN_CONTAINER_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-component-extensions-with-background-pages",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-features=Translate,OptimizationHints,MediaRouter,DialMediaRouteProvider,AudioServiceSandbox",
    "--disable-hang-monitor",
    "--disable-ipc-flooding-protection",
    "--disable-popup-blocking",
    "--disable-prompt-on-repost",
    "--disable-renderer-backgrounding",
    "--disable-sync",
    "--force-color-profile=srgb",
    "--metrics-recording-only",
    "--mute-audio",
    "--no-first-run",
    "--no-default-browser-check",
    "--password-store=basic",
    "--use-mock-keychain",
]

def launch_universal_playwright_browser(p, headless=True):
    """
    Universal Playwright Chromium Launcher (Sync):
    - On ARM64 (Mini PC / Raspberry Pi): Launches system Chromium via CDP.
    - On x86_64 (Intel / AMD / Dev Laptops): Launches Playwright's bundled Chromium with optimized flags.
    
    Returns:
        (browser, process_handle)
    """
    if is_arm_architecture():
        cdp_port = get_free_port()
        chromium_bin = "/usr/lib/chromium/chromium" if os.path.exists("/usr/lib/chromium/chromium") else "/usr/bin/chromium"
        user_data_dir = tempfile.mkdtemp(prefix=f"chrome_cdp_{cdp_port}_")
        log_path = os.path.join(user_data_dir, "chromium.log")
        log_file = open(log_path, "w+")
        
        chrome_args = [
            chromium_bin,
            *LEAN_CONTAINER_CHROMIUM_ARGS,
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
        ]
        if headless:
            chrome_args.append("--headless=new")

        proc = subprocess.Popen(chrome_args, stdout=log_file, stderr=log_file)
        proc._user_data_dir = user_data_dir
        proc._log_file = log_file

        try:
            _wait_for_cdp_ready(cdp_port, proc, log_file, timeout=30.0)
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            return browser, proc
        except Exception as e:
            if proc:
                kill_process_tree(proc)
            raise RuntimeError(f"Failed to connect to ARM System Chromium via CDP: {e}")
    else:
        browser = p.chromium.launch(headless=headless, args=OPTIMIZED_CHROMIUM_ARGS)
        return browser, None

@contextmanager
def universal_browser_session(p, headless=True):
    """
    Guaranteed Leak-Proof Sync Context Manager:
    Embeds a try...finally block ensuring both Playwright browser connection and Chromium
    subprocess are 100% closed & killed even if a scraping error or process failure occurs.
    """
    browser = None
    proc = None
    try:
        browser, proc = launch_universal_playwright_browser(p, headless=headless)
        yield browser, proc
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if proc:
            kill_process_tree(proc)

async def async_launch_universal_playwright_browser(p, headless=True):
    """Async variant of launch_universal_playwright_browser."""
    if is_arm_architecture():
        cdp_port = get_free_port()
        chromium_bin = "/usr/lib/chromium/chromium" if os.path.exists("/usr/lib/chromium/chromium") else "/usr/bin/chromium"
        user_data_dir = tempfile.mkdtemp(prefix=f"chrome_cdp_{cdp_port}_")
        log_path = os.path.join(user_data_dir, "chromium.log")
        log_file = open(log_path, "w+")
        
        chrome_args = [
            chromium_bin,
            *LEAN_CONTAINER_CHROMIUM_ARGS,
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
        ]
        if headless:
            chrome_args.append("--headless=new")

        proc = subprocess.Popen(chrome_args, stdout=log_file, stderr=log_file)
        proc._user_data_dir = user_data_dir
        proc._log_file = log_file

        try:
            await _async_wait_for_cdp_ready(cdp_port, proc, log_file, timeout=30.0)
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            return browser, proc
        except Exception as e:
            if proc:
                kill_process_tree(proc)
            raise RuntimeError(f"Failed to connect to ARM System Chromium via CDP: {e}")
    else:
        browser = await p.chromium.launch(headless=headless, args=OPTIMIZED_CHROMIUM_ARGS)
        return browser, None

@asynccontextmanager
async def async_universal_browser_session(p, headless=True):
    """
    Guaranteed Leak-Proof Async Context Manager:
    Embeds a try...finally block ensuring both Playwright browser connection and Chromium
    subprocess are 100% closed & killed even if a scraping error or process failure occurs.
    """
    browser = None
    proc = None
    try:
        browser, proc = await async_launch_universal_playwright_browser(p, headless=headless)
        yield browser, proc
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if proc:
            kill_process_tree(proc)

async def setup_resource_blocking(page):
    """
    Aborts requests for images, media, fonts, and third-party trackers.
    Drastically cuts down memory footprint and boosts page loading speeds.
    """
    blocked_types = {"image", "media", "font"}
    blocked_patterns = ["google-analytics", "googletagmanager", "facebook", "doubleclick", "clarity.ms", "sentry"]

    async def _route_handler(route):
        try:
            req = route.request
            if req.resource_type in blocked_types:
                await route.abort()
                return
            url_lower = req.url.lower()
            if any(p in url_lower for p in blocked_patterns):
                await route.abort()
                return
            await route.continue_()
        except Exception:
            pass

    await page.route("**/*", _route_handler)

def setup_resource_blocking_sync(page):
    """Sync variant of setup_resource_blocking."""
    blocked_types = {"image", "media", "font"}
    blocked_patterns = ["google-analytics", "googletagmanager", "facebook", "doubleclick", "clarity.ms", "sentry"]

    def _route_handler(route):
        try:
            req = route.request
            if req.resource_type in blocked_types:
                route.abort()
                return
            url_lower = req.url.lower()
            if any(p in url_lower for p in blocked_patterns):
                route.abort()
                return
            route.continue_()
        except Exception:
            pass

    page.route("**/*", _route_handler)
