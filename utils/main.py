# main.py — FINAL COMPATIBLE VERSION (WITH DEAL BOOSTER) + guaranteed browser clean-up
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import *
import time
import os
import json
from selenium.webdriver.common.keys import Keys
import re
import requests
from datetime import datetime
import threading
import platform
from pathlib import Path

class FatalBotError(Exception):
    """Raised to stop bot immediately with a short code (no long traceback spam)."""
    pass


# ============================================================
# LOGGING SYSTEM
# ============================================================
class BotLogger:
    """Centralized logging system that writes to file and shared location for UI"""
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self, session_id=None):
        self.session_id = session_id or f"session_{int(time.time())}"
        self.log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        
        # Log file for this session
        self.log_file = os.path.join(self.log_dir, f"bot_{self.session_id}.log")
        
        # Shared log file for UI (latest session)
        self.shared_log_file = os.path.join(self.log_dir, "latest.log")
        
        # Initialize log files
        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write(f"=== Bot Session Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        
        with open(self.shared_log_file, 'w', encoding='utf-8') as f:
            f.write(f"=== Bot Session Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    
    @classmethod
    def get_instance(cls, session_id=None):
        """Get or create singleton logger instance"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(session_id)
        return cls._instance
    
    def log(self, message, level="INFO"):
        """Log a message to both file and shared location"""
        # #region agent log
        import json; log_file = r"c:\Users\zgarm\OneDrive\Desktop\flipkart automation\.cursor\debug.log"; open(log_file, "a", encoding="utf-8").write(json.dumps({"location":"main.py:59","message":"BotLogger.log entry","data":{"message":repr(message),"has_backslash_n":"\\n" in str(message),"level":level,"hypothesisId":"B"},"timestamp":int(__import__("time").time()*1000)})+"\n")
        # #endregion
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level}] {message}"
        # #region agent log
        open(log_file, "a", encoding="utf-8").write(json.dumps({"location":"main.py:62","message":"BotLogger.log_entry created","data":{"log_entry":repr(log_entry),"has_backslash_n":"\\n" in log_entry,"hypothesisId":"B"},"timestamp":int(__import__("time").time()*1000)})+"\n")
        # #endregion
        
        # Write to session log file
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry + '\n')
                f.flush()
        except Exception as e:
            print(f"Error writing to log file: {e}")
        
        # Write to shared log file (for UI)
        try:
            with open(self.shared_log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry + '\n')
                f.flush()
        except Exception as e:
            print(f"Error writing to shared log file: {e}")
        
        # Also print to console (for debugging)
        print(log_entry)
    
    def success(self, message):
        """Log success message"""
        self.log(f"✅ {message}", "SUCCESS")
    
    def error(self, message):
        """Log error message"""
        self.log(f"❌ {message}", "ERROR")
    
    def warning(self, message):
        """Log warning message"""
        self.log(f"⚠️ {message}", "WARNING")
    
    def info(self, message):
        """Log info message"""
        self.log(f"ℹ️ {message}", "INFO")
    
    def fatal(self, message):
        """Log fatal message"""
        self.log(f"💀 FATAL: {message}", "FATAL")
    
    def step(self, step_name, status="STARTED"):
        """Log step with status"""
        status_emoji = {
            "STARTED": "🚀",
            "SUCCESS": "✅",
            "FAILED": "❌",
            "SKIPPED": "⏭️"
        }
        emoji = status_emoji.get(status, "ℹ️")
        self.log(f"{emoji} STEP: {step_name} - {status}", "STEP")


class FlipkartSniper:
    def __init__(self, phone_number, address_data, products_dict, max_price=9999,
                 coupon="None", deal_keyword="", auto_apply_deals=True, session_id=None, headless=None, allow_less_qty=True, screenshot_base_url_arg=None):
        self.now = time.perf_counter()
        self.driver = None
        self.coupon = coupon
        self.fatal_error = False
        self.fatal_code = None
        self.order_id = "NOT_FOUND"
        self.screenshot_url = "NONE" 
        self.products = products_dict
        self.max_price = max_price
        self.deal_keyword = deal_keyword
        self.auto_apply_deals = auto_apply_deals
        self.allow_less_qty = allow_less_qty
        # Track coupon interaction state
        self.apply_button_used = False  # true if a pre-loaded Apply button was clicked
        self.coupon_filled = False      # true if we manually entered a coupon code
        
        # Store session_id for use in deal selection modal
        self.session_id = session_id or f"session_{int(time.time())}"
        # Initialize logger
        self.logger = BotLogger.get_instance(session_id)
        # Get absolute path to chromedriver (Windows: .exe, Linux: no extension)
        # Use Selenium Manager (auto-detect)
        self.service = Service()

        self.FLIPKART_LOGIN_URL = "https://www.flipkart.com/login?type=email&verificationType=password&sourceContext=default&ret=%2F"
        self.PHONE_NUMBER = phone_number
        self.ADDRESS_DATA = address_data
        self.ADD_ADDRESS_URL = "https://www.flipkart.com/rv/accounts/addaddress?source=entry&marketplace=FLIPKART&bsRevamped=true"
        # Absolute screenshots dir to build public/local links
        self.screenshots_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "screenshots"))
        os.makedirs(self.screenshots_dir, exist_ok=True)
        
        # Determine base URL for screenshots
        # 1. Use passed argument if valid
        # 2. Use SCREENSHOT_BASE_URL env var
        # 3. Use SCREENSHOT_DOMAIN env var
        # 4. Fallback to localhost
        
        if screenshot_base_url_arg and screenshot_base_url_arg.strip():
             # Ensure protocol
             arg_url = screenshot_base_url_arg.strip()
             if not arg_url.startswith("http"):
                 arg_url = f"https://{arg_url}"
             # Ensure /screenshots suffix if not present
             if not arg_url.endswith("/screenshots"):
                  arg_url = f"{arg_url.rstrip('/')}/screenshots"
             self.screenshot_base_url = arg_url
        elif os.environ.get("SCREENSHOT_BASE_URL"):
            # Full URL override
            self.screenshot_base_url = os.environ.get("SCREENSHOT_BASE_URL")
        else:
            # Use domain from env or default to localhost
            custom_domain = os.environ.get("SCREENSHOT_DOMAIN", "").strip()
            use_https = os.environ.get("SCREENSHOT_HTTPS", "false").lower() == "true"
            
            if custom_domain:
                # Check if domain already includes protocol
                if custom_domain.startswith("http://") or custom_domain.startswith("https://"):
                    # Full URL provided, extract domain and port
                    from urllib.parse import urlparse
                    parsed = urlparse(custom_domain)
                    domain = parsed.netloc or parsed.path
                    if not domain:
                        domain = custom_domain.replace("http://", "").replace("https://", "")
                    protocol = "https" if custom_domain.startswith("https://") else "http"
                    # If no port in domain, add default port (or skip for HTTPS 443)
                    if ":" not in domain:
                        if protocol == "https":
                            domain_with_port = domain  # HTTPS typically uses 443 (no need to specify)
                        else:
                            port = os.environ.get("FLASK_PORT", "5000")
                            domain_with_port = f"{domain}:{port}"
                    else:
                        domain_with_port = domain
                    self.screenshot_base_url = f"{protocol}://{domain_with_port}/screenshots"
                else:
                    # Domain only, determine protocol
                    protocol = "https" if use_https else "http"
                    # If domain includes port, use it; otherwise default
                    if ":" in custom_domain:
                        domain_with_port = custom_domain
                    else:
                        if use_https:
                            # HTTPS typically uses port 443 (no need to specify)
                            domain_with_port = custom_domain
                        else:
                            port = os.environ.get("FLASK_PORT", "5000")
                            domain_with_port = f"{custom_domain}:{port}"
                    self.screenshot_base_url = f"{protocol}://{domain_with_port}/screenshots"
            else:
                # Default to localhost
                port = os.environ.get("FLASK_PORT", "5000")
                self.screenshot_base_url = f"http://localhost:{port}/screenshots"
        self.options = webdriver.ChromeOptions()
        self.options.set_capability("pageLoadStrategy", "eager")  # Speed up: don't wait for full assets
        
 
        
        # Headless & VPS Optimization Logic
        # ---------------------------------
        is_linux = platform.system() == "Linux"
        should_be_headless = headless

        # If headless not explicitly set:
        # - Linux: Default to TRUE (crucial for VPS)
        # - Windows: Default to FALSE (unless user requested optimization)
        if should_be_headless is None:
            should_be_headless = is_linux

        if should_be_headless:
            self.logger.info("Running in HEADLESS mode (VPS optimized)")
            self.options.add_argument("--headless=new")  # Enable headless mode for VPS
            self.options.add_argument("--window-size=1920,1080")
            # Hide scrollbars in headless to avoid screenshot issues
            self.options.add_argument("--hide-scrollbars")
        
        # Critical Stability Flags (Essential for VPS)
        self.options.add_argument("--no-sandbox")
        self.options.add_argument("--disable-dev-shm-usage")  # Fixes crash on low shm
        self.options.add_argument("--disable-gpu")
        self.options.add_argument("--disable-software-rasterizer")
        self.options.add_argument("--disable-setuid-sandbox")
        
        # Network & Process Stability
        self.options.add_argument("--disable-extensions")
        self.options.add_argument("--dns-prefetch-disable")
        self.options.add_argument("--disable-application-cache")
        # REMOVED: --remote-debugging-port can cause 'unable to connect to renderer' errors
        
        # Extra stability for low-resource VPS (Linux-specific)
        if is_linux:
            # Use multi-process mode for better stability (single-process can cause crashes)
            # Only use single-process if absolutely necessary for very low-memory VPS
            # self.options.add_argument("--single-process")  # Disabled - causes instability
            # self.options.add_argument("--disable-zygote")  # Disabled - can cause crashes
            # Additional Linux-specific stability flags
            self.options.add_argument("--disable-backgrounding-occluded-windows")
            self.options.add_argument("--disable-background-timer-throttling")
            self.options.add_argument("--disable-renderer-backgrounding")
            self.options.add_argument("--disable-features=RendererScheduling")

        # Enhanced Stability and Performance Flags (Aggressive Optimization)
        # Apply to crucial stability and anti-crash settings
        self.options.add_argument("--disable-infobars")
        self.options.add_argument("--disable-notifications")
        self.options.add_argument("--disable-popup-blocking")
        self.options.add_argument("--ignore-certificate-errors")
        self.options.add_argument("--disable-blink-features=AutomationControlled") # Prevent detection crashes
        self.options.add_argument("--disable-features=VizDisplayCompositor")
        self.options.add_argument("--disable-features=IsolateOrigins,site-per-process") # Crucial for memory reduction
        self.options.add_argument("--disable-browser-side-navigation")
        self.options.add_argument("--disable-gpu-sandbox")
        self.options.add_argument("--disable-accelerated-2d-canvas")
        self.options.add_argument("--disable-background-networking")
        self.options.add_argument("--disable-default-apps")
        self.options.add_argument("--disable-sync")
        self.options.add_argument("--disable-translate")
        self.options.add_argument("--hide-scrollbars")
        self.options.add_argument("--metrics-recording-only")
        self.options.add_argument("--mute-audio")
        self.options.add_argument("--no-first-run")
        self.options.add_argument("--safebrowsing-disable-auto-update")
        # Anti-detection experimental options
        self.options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.options.add_experimental_option("useAutomationExtension", False)

        # FIX: Screenshot URL for VPS (Public IP detection)
        if self.screenshot_base_url.startswith("http://localhost"):
            try:
                # If running on Linux/VPS, try to get public IP
                if is_linux:
                    import socket
                    # Try to get local network IP first
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.settimeout(0)
                    try:
                        # doesn't even have to be reachable
                        s.connect(('10.254.254.254', 1))
                        local_ip = s.getsockname()[0]
                    except Exception:
                        local_ip = '127.0.0.1'
                    finally:
                        s.close()
                    
                    # Update base URL to use local network IP (accessible via VPN/public if forwarded)
                    # For true public IP, user should set SCREENSHOT_DOMAIN env var
                    port = os.environ.get("FLASK_PORT", "5000")
                    self.screenshot_base_url = f"http://{local_ip}:{port}/screenshots"
                    self.logger.info(f"Updated Screenshot URL to: {self.screenshot_base_url}")
            except Exception:
                pass
        
        # Anti-detection & Performance
        self.options.add_argument("--disable-blink-features=AutomationControlled")
        self.options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.options.add_experimental_option("useAutomationExtension", False)
        
        # Resource optimization
        self.options.add_argument("--disable-background-networking")
        self.options.add_argument("--disable-features=TranslateUI,AudioServiceOutOfProcess,IsolateOrigins,site-per-process")
        self.options.add_argument("--disable-ipc-flooding-protection")
        self.options.add_argument("--disable-infobars")
        self.options.add_argument("--disable-notifications")
        self.options.add_argument("--disable-sync")
        self.options.add_argument("--metrics-recording-only")
        self.options.add_argument("--no-first-run")
        self.options.add_argument("--ignore-certificate-errors")
        
        # Memory optimization (reduced for VPS stability)
        self.options.add_argument("--memory-pressure-off")
        self.options.add_argument("--js-flags=--max-old-space-size=256")  # Reduced from 512 for VPS
        self.options.add_argument("--max_old_space_size=256")  # Additional memory limit
        
        # Linux-specific optimizations (consolidated, no duplicates)
        if platform.system() == "Linux":
            # Additional stability flags for Linux VPS
            self.options.add_argument("--disable-breakpad")  # Disable crash reporting
            self.options.add_argument("--disable-crash-reporter")  # Disable crash reporter
            self.options.add_argument("--disable-logging")  # Reduce logging overhead
            self.options.add_argument("--log-level=3")  # Only fatal errors
            self.options.add_argument("--silent")  # Suppress output

        # Allow geolocation
        self.options.add_argument("--enable-geolocation")
        self.options.add_argument("--deny-permission-prompts=false")
        self.options.add_argument("--unsafely-treat-insecure-origin-as-secure=https://www.flipkart.com")

        # FIX: Allow geolocation automatically
        prefs = {
            "profile.default_content_setting_values.geolocation": 1,
            "profile.default_content_settings.popups": 0,
        }
        self.options.add_experimental_option("prefs", prefs)

        mobile_emulation = {
    "deviceName": "Pixel 7"
}
        self.options.add_experimental_option("mobileEmulation", mobile_emulation)

    # -----------------------
    # Fatal handler helper
    # -----------------------


    def _fatal(self, code):
        """Stop bot immediately on any error. This function MUST be called for all errors."""
        self.fatal_error = True
        self.fatal_code = code
        timestamp = int(time.time())
        screenshot_filename = f"{code}_{timestamp}.png"
        # Save all fatal screenshots into the same screenshots_dir used for orders
        screenshot_path = os.path.join(self.screenshots_dir, screenshot_filename)

        self.logger.fatal(f"{code} → STOPPING BOT IMMEDIATELY")
        self.logger.log(f"{'='*60}", "FATAL")

        # Capture screenshot
        try:
            if self.driver and self._check_driver_health():
                self.driver.save_screenshot(screenshot_path)
                self.logger.log(f"Screenshot saved: {screenshot_path}", "FATAL")
                # Generate HTTP URL for local Flask server (like imgbb but local)
                base = self.screenshot_base_url.rstrip("/")
                self.screenshot_url = f"{base}/{screenshot_filename}"
                self.logger.log(f"Screenshot URL: {self.screenshot_url}", "FATAL")
            else:
                self.logger.warning("Driver not available for screenshot capture")
        except Exception as e:
            self.logger.error(f"Could not capture screenshot: {e}")

        # Quit browser safely
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None  # Clear reference to prevent double-quit
                self.logger.log("Browser closed", "FATAL")
        except Exception as e:
            self.logger.error(f"Error closing browser: {e}")
            self.driver = None

        # Raise exception to stop execution immediately
        raise FatalBotError(code)


    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------
    def q(self, t=3):
        return WebDriverWait(self.driver, t, poll_frequency=0.3, ignored_exceptions=[
            NoSuchElementException, StaleElementReferenceException, 
            TimeoutException, WebDriverException
        ])

    def find_element_with_retry(self, xpaths, timeout=5, retries=1, error_code="ELEMENT_NOT_FOUND"):
        """
        Find element using multiple XPath fallbacks with a single quick pass.
        Uses find_elements (no waits) and fails fast.
        """
        for xpath in xpaths:
            elements = self.driver.find_elements(By.XPATH, xpath)
            for el in elements:
                if el.is_displayed():
                    return el
        # If not found, fatal immediately
        self.logger.error(f"Element not found (xpaths tried: {len(xpaths)})")
        self._fatal(error_code)
        return None
    
    def find_clickable_with_retry(self, xpaths, timeout=5, retries=1, error_code="ELEMENT_NOT_FOUND"):
        """
        Find clickable element using multiple XPath fallbacks with a single quick pass.
        Uses find_elements and fails fast.
        """
        for xpath in xpaths:
            elements = self.driver.find_elements(By.XPATH, xpath)
            for el in elements:
                try:
                    if el.is_displayed() and el.is_enabled():
                        return el
                except Exception:
                    continue
        self.logger.error(f"Clickable element not found (xpaths tried: {len(xpaths)})")
        self._fatal(error_code)
        return None

    def safe_click(self, element, retries=3):
        """Click element with multiple retry strategies"""
        if not element:
            self.logger.error("Cannot click: element is None")
            self._fatal("CLICK_FAILED")
        
        for attempt in range(retries):
            try:
                # Scroll into view first
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center', behavior:'auto'});", element)
                time.sleep(0.3)
                
                # Try JavaScript click first (most reliable)
                self.driver.execute_script("arguments[0].click();", element)
                time.sleep(0.4)
                return True
            except StaleElementReferenceException:
                if attempt < retries - 1:
                    self.logger.warning(f"Stale element on click attempt {attempt+1}, retrying...")
                    time.sleep(0.5)
                    continue
            except Exception as e:
                if attempt < retries - 1:
                    try:
                        # Try regular click
                        element.click()
                        time.sleep(0.2)
                        return True
                    except Exception:
                        pass
                if attempt == retries - 1:
                    self.logger.error(f"All click attempts failed: {e}")
                    self._fatal("CLICK_FAILED")
        return False

    def clear_and_send(self, element, text):
        # #region agent log
        import json; log_file = r"c:\Users\zgarm\OneDrive\Desktop\flipkart automation\.cursor\debug.log"; open(log_file, "a", encoding="utf-8").write(json.dumps({"location":"main.py:445","message":"clear_and_send entry","data":{"text":repr(text),"has_backslash_n":"\\n" in str(text),"hypothesisId":"C"},"timestamp":int(__import__("time").time()*1000)})+"\n")
        # #endregion
        element.clear()
        element.send_keys(Keys.CONTROL + "a")
        element.send_keys(Keys.DELETE)
        element.send_keys(text)
        # #region agent log
        open(log_file, "a", encoding="utf-8").write(json.dumps({"location":"main.py:449","message":"clear_and_send completed","data":{"text_sent":repr(text),"hypothesisId":"C"},"timestamp":int(__import__("time").time()*1000)})+"\n")
        # #endregion

    def screenshot(self, name):
        # only attempt screenshot if driver seems alive
        try:
            if self.driver:
                self.driver.save_screenshot(f"screenshots/{name}_{int(time.time())}.png")
        except Exception:
            # don't spam errors if screenshot fails
            pass

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------
    def step_login(self, otp_supplier):
        self.logger.step("LOGIN", "STARTED")
        if not self._check_driver_health():
            self._fatal("DRIVER_UNRESPONSIVE")
        self.driver.get(self.FLIPKART_LOGIN_URL)
        time.sleep(1)
        login_input = self.q(5).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//input[contains(@class,'jwCbxy') and (@type='text' or @type='email')]"
            ))
        )
        self.clear_and_send(login_input, self.PHONE_NUMBER)
        self.logger.info(f"Entered login ID: {self.PHONE_NUMBER}")
        self.safe_click(
            self.q(5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@class,'xqOMQN')]"))
            )
        )
        self.logger.info("Waiting for Flipkart OTP via email...")
        for attempt in range(14):
            OTP_CODE = otp_supplier(self.PHONE_NUMBER)
            if OTP_CODE:
                self.logger.success(f"Got OTP: {OTP_CODE}")
                break
            self.logger.info(f"OTP not received yet (attempt {attempt+1}/14), retrying...")
            time.sleep(2)
        else:
            # OTP failure is fatal for this run
            self._fatal("OTP_NOT_RECEIVED")

        self.q(5).until(
            EC.element_to_be_clickable((By.XPATH, "//input[contains(@class,'S1KmoO')]"))
        ).send_keys(OTP_CODE)
        self.safe_click(
            self.q(5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@class,'xqOMQN')]"))
            )
        )
      
        self.logger.step("LOGIN", "SUCCESS")
        time.sleep(1)

    # ------------------------------------------------------------------
    # Address
    # ------------------------------------------------------------------
    def step_add_address(self):
        self.logger.step("ADDRESS", "STARTED")
        self.logger.info("Navigating to address page...")
        self.driver.get(self.ADD_ADDRESS_URL)
        time.sleep(2)
        try:
            self.safe_click(self.driver.find_element(By.XPATH, "//button[text()='CANCEL']"))
            self.logger.info("Dismissed cancel button if present")
        except Exception:
            pass
        self.logger.info(f"Filling name: {self.ADDRESS_DATA['name']}")
        self.clear_and_send(self.q(5).until(EC.presence_of_element_located((By.NAME, "name"))), self.ADDRESS_DATA["name"])
        self.logger.info(f"Filling phone: {self.ADDRESS_DATA['phone']}")
        self.clear_and_send(self.q(5).until(EC.presence_of_element_located((By.NAME, "phone"))), self.ADDRESS_DATA["phone"])
        self.logger.info(f"Filling pincode: {self.ADDRESS_DATA['pincode']}")
        self.clear_and_send(self.q(5).until(EC.presence_of_element_located((By.NAME, "pincode"))), self.ADDRESS_DATA["pincode"])
        self.logger.info(f"Filling address line 1: {self.ADDRESS_DATA['address_line1']}")
        self.clear_and_send(self.q(5).until(EC.presence_of_element_located((By.NAME, "addressLine1"))), self.ADDRESS_DATA["address_line1"])
        self.logger.info(f"Filling address line 2: {self.ADDRESS_DATA['address_line2']}")
        self.clear_and_send(self.q(5).until(EC.presence_of_element_located((By.NAME, "addressLine2"))), self.ADDRESS_DATA["address_line2"])
        time.sleep(2)
        self.logger.info("Clicking Save Address button...")
        self.safe_click(self.q(5).until(EC.element_to_be_clickable((By.XPATH, "//input[@value='Save Address']"))))
        time.sleep(1.3)
        self.logger.step("ADDRESS", "SUCCESS")

        # Debug screenshot after address save
        try:
            ts = int(time.time())
            path = f"screenshots/address_debug_{ts}.png"
            self.driver.save_screenshot(path)
            self.logger.info(f"Address Debug Screenshot saved at: {path}")
        except:
            pass

    # ------------------------------------------------------------------
    # Clear cart
    # ------------------------------------------------------------------
    def step_clear_cart(self):
        self.logger.step("CLEAR_CART", "STARTED")
        self.logger.info("Navigating to cart page...")
        self.driver.get("https://www.flipkart.com/viewcart?marketplace=GROCERY")
        time.sleep(0.5)  # Give page time to load
        removed_count = 0
        
        max_attempts = 50
        attempt = 0
        
        while attempt < max_attempts:
            attempt += 1
            removed = False
            
            # Updated XPaths to match the actual HTML structure
            for xpath in [
                "//div[contains(@class, 'css-1rynq56') and contains(text(), 'Remove')]",
                "//div[@dir='auto' and contains(text(), 'Remove ')]",
                "//div[text()='Remove ']"
            ]:
                try:
                    elements = self.driver.find_elements(By.XPATH, xpath)
                    for el in elements:
                        if el.is_displayed():
                            # Click the parent div which is the actual clickable button
                            parent = el.find_element(By.XPATH, "..")
                            self.safe_click(parent)
                            time.sleep(0.2)
                            
                            # Try to click confirm button
                            try:
                                confirm_btns = self.driver.find_elements(By.XPATH, 
                                    "//button[contains(text(), 'Remove') or contains(text(), 'REMOVE')]")
                                for btn in confirm_btns:
                                    if btn.is_displayed():
                                        self.safe_click(btn)
                                        break
                                time.sleep(0.2)
                            except Exception:
                                pass
                            
                            removed = True
                            removed_count += 1
                            self.logger.info(f"Removed item #{removed_count} from cart")
                            time.sleep(0.2)
                            break
                except Exception as e:
                    pass
                
                if removed:
                    break
            
            if not removed:
                break
        
        if removed_count > 0:
            self.logger.info(f"Cart cleared: removed {removed_count} item(s)")
        else:
            self.logger.info("Cart is already empty")
        self.logger.step("CLEAR_CART", "SUCCESS")
    # ------------------------------------------------------------------
    # Add single product
    # ------------------------------------------------------------------
    def _record_stock_warning(self, product_name, product_url, desired_qty, current_qty):
        """Write a stock warning file for UI to pick up."""
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            warning_path = os.path.join(base_dir, "..", "download", "stock_warning.json")
            
            # Read existing warnings (if any) to append to list
            warnings_list = []
            if os.path.exists(warning_path):
                try:
                    import json
                    with open(warning_path, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                        if isinstance(existing_data, list):
                            warnings_list = existing_data
                        elif isinstance(existing_data, dict):
                            warnings_list = [existing_data]
                except:
                    pass
            
            # Add new warning
            payload = {
                "product_name": product_name,
                "product_url": product_url,
                "desired_qty": int(desired_qty),
                "current_qty": int(current_qty),
                "timestamp": int(time.time()),
                "resolved": False
            }
            
            # Only add if not already in list (avoid duplicates)
            if not any(w.get("product_url") == product_url and w.get("desired_qty") == desired_qty for w in warnings_list):
                warnings_list.append(payload)
            
            import json
            with open(warning_path, "w", encoding="utf-8") as f:
                json.dump(warnings_list, f, ensure_ascii=False, indent=2)
            self.logger.warning(
                f"[STOCK] Desired qty {desired_qty} > available {current_qty} for product '{product_name}'"
            )
        except Exception as e:
            self.logger.error(f"[STOCK] Failed to write stock warning: {e}")

    def step_add_single_product(self, product_url, desired_qty):
        self.logger.info(f"Adding product: {product_url} | Desired Qty: {desired_qty}")
        # Retry navigation to handle renderer timeouts
        for attempt in range(3):
            try:
                self.driver.get(product_url)
                break
            except (TimeoutException, WebDriverException) as e:
                self.logger.warning(f"Navigation failed (attempt {attempt+1}/3): {e}")
                if attempt == 2:
                    self.logger.error("Failed to load product page after 3 attempts")
                    self._fatal("PAGE_LOAD_FAILED")
                time.sleep(3)
        
        # Give page time to load and React components to settle (Grocery is slow)
        time.sleep(3)

        # Get product name with robust fallbacks
        product_name = "Unknown Product"
        try:
            # wait briefly for any title element
            name_selector = "span.B_NuCI, h1.yhB1nd, h1, div.css-1rynq56.r-8akbws.r-krxsd3"
            try:
                product_name_element = self.driver.find_element(By.CSS_SELECTOR, name_selector)
                product_name = product_name_element.text.strip()
            except:
                # Fallback to the complex React class
                product_name_element = self.driver.find_element(By.CSS_SELECTOR, "div.css-1rynq56.r-8akbws.r-krxsd3.r-dnmrzs.r-1udh08x.r-1udbk01")
                product_name = product_name_element.text.strip()
            
            self.logger.info(f"Product Name: {product_name}")
            # Give page one more second to settle before clicking critical buttons
            time.sleep(1)
        except Exception as e:
            try:
                 h1s = self.driver.find_elements(By.TAG_NAME, "h1")
                 for h in h1s:
                     if h.is_displayed() and len(h.text.strip()) > 5:
                         product_name = h.text.strip()
                         self.logger.info(f"Product Name (fallback): {product_name}")
                         break
            except:
                self.logger.warning(f"Could not extract product name: {e}")

        # Try to dismiss any potential location picker / overlay 
        # try:
        #     # Clicking body helps clear some focus-based overlays
        #     self.driver.find_element(By.TAG_NAME, "body").click()
        #     time.sleep(0.5)
        #     # Find and click cross/close buttons
        #     close_buttons = self.driver.find_elements(By.XPATH, "//div[contains(@class,'close')] | //img[contains(@src,'cross')] | //div[text()='✕']")
        #     for cb in close_buttons:
        #         if cb.is_displayed():
        #             cb.click()
        #             time.sleep(0.5)
        # except:
        #     pass

        # Click Add - comprehensive Grocery selectors
        add_button = None
        add_xpaths = [
            "//div[text()='Add']",
            "//div[text()='ADD']",
            "//div[normalize-space(text())='Add']",
            "//div[normalize-space(text())='ADD']",
            "//div[contains(text(), 'Add') and contains(@class, 'r-1777fci')]",
            "//div[contains(text(), 'ADD') and contains(@class, 'r-1777fci')]",
            "//div[normalize-space(text())='Add to cart' or normalize-space(text())='ADD TO CART']",
            "//div[contains(@class, 'r-1m93j0t')]//div[text()='Add' or text()='ADD']",
        ]

        self.logger.info("Looking for Add button...")
        time.sleep(1.0) # Brief pause before search
        for xpath in add_xpaths:
            try:
                btns = self.driver.find_elements(By.XPATH, xpath)
                for btn in btns:
                    if btn.is_displayed():
                        add_button = btn
                        break
                if add_button: break
            except: continue

        # Recovery scroll attempt
        if not add_button:
            self.logger.info("Add button not found, performing recovery scroll...")
            for scroll_amt in [400, 800]:
                self.driver.execute_script(f"window.scrollBy(0, {scroll_amt});")
                time.sleep(1)
                for xpath in add_xpaths:
                    try:
                        btns = self.driver.find_elements(By.XPATH, xpath)
                        for btn in btns:
                            if btn.is_displayed():
                                add_button = btn
                                break
                        if add_button: break
                    except: continue
                if add_button: break

        try:
            if not add_button:
                raise NoSuchElementException("Add button not found")
            
            # Explicit scroll + pause before clicking (Critical for VPS)
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", add_button)
                time.sleep(1.0)
            except: pass
                
            # Robust click mechanism (Standard -> JS -> Retry)
            clicked = False
            for i in range(3):
                try:
                    add_button.click()
                    clicked = True
                    self.logger.info("Standard click successful")
                    break
                except Exception as e:
                    self.logger.warning(f"Standard click failed: {e}, trying JS click...")
                    try:
                        self.driver.execute_script("arguments[0].click();", add_button)
                        clicked = True
                        self.logger.info("JS click successful")
                        break
                    except Exception as js_e:
                        self.logger.warning(f"JS click failed: {js_e}")
                        time.sleep(1)
            
            if not clicked:
                self.logger.error("All click attempts failed for Add button")
            
            time.sleep(2.5) # Increased wait for 'Add' -> 'Qty' transition
            self.logger.info("Add button interaction completed")
        except Exception:
            # Product "Add" button not present → treat as OOS
            self.logger.error("Add button not found - perform OOS debug scroll")
            
            # Scroll down to capture more context in screenshot
            try:
                self.driver.execute_script("window.scrollTo(0, 1000);") 
                time.sleep(0.5)
                # Physical keys
                try:
                    body = self.driver.find_element(By.TAG_NAME, "body")
                    body.click()
                    for _ in range(5):
                        body.send_keys(Keys.PAGE_DOWN)
                        time.sleep(0.2)
                except: pass
            except Exception: pass
                
            # Local screenshot
            try:
                ts = int(time.time())
                path = f"screenshots/PRODUCT_OOS_SCROLL_{ts}.png"
                self.driver.save_screenshot(path)
                self.logger.info(f"OOS Context Screenshot saved at: {path}")
            except: pass

            self._fatal("PRODUCT_OUT_OF_STOCK")

        qty_xpath = "//div[contains(@class,'r-1cenzwm') and contains(@class,'r-1b43r93')]"
        increase_btn_xpath = "(//div[contains(@style,'rgb(133, 60, 14)')])[last()]"

        # Two attempts to update quantity and find maximum available
        # Helper for converting text to quantity safely
        def safe_get_qty(element):
            try:
                txt = element.text.strip()
                # Check value attribute for inputs
                if not txt:
                    txt = element.get_attribute("value") or ""
                
                if not txt:
                    return 0
                
                digits = "".join(filter(str.isdigit, txt))
                return int(digits) if digits else 0
            except:
                return 0

        # Two attempts to update quantity and find maximum available
        max_available_qty = 0
        for attempt in range(1, 3):
            try:
                qty_el = self.q(4).until(EC.presence_of_element_located((By.XPATH, qty_xpath)))
                current_qty = safe_get_qty(qty_el)
                
                # Retry if 0 and we expect >0 (maybe loading)
                if current_qty == 0:
                    time.sleep(0.5)
                    current_qty = safe_get_qty(qty_el)
                
                max_available_qty = max(max_available_qty, current_qty)

                if current_qty >= desired_qty:
                    self.logger.info(f"Quantity OK: {current_qty}/{desired_qty}")
                    break

                missing = desired_qty - current_qty
                self.logger.info(f"Attempt {attempt}/2 → Current: {current_qty}, Missing: {missing}")

                # Try to increase quantity
                increase_count = 0
                for _ in range(missing):
                    try:
                        btn = self.q(2).until(EC.element_to_be_clickable((By.XPATH, increase_btn_xpath)))
                        self.safe_click(btn)
                        time.sleep(0.8)
                        increase_count += 1
                    except Exception:
                        # If + button disappears or isn't clickable then product can't be increased further
                        self.logger.warning("Could not increase quantity further - reached maximum available")
                        break

                # Read the quantity after attempting to increase
                time.sleep(1.5)
                try:
                    qty_el = self.q(4).until(EC.presence_of_element_located((By.XPATH, qty_xpath)))
                    final_qty = safe_get_qty(qty_el)
                    max_available_qty = max(max_available_qty, final_qty)
                    
                    # Check if we've reached the maximum available quantity
                    if final_qty == current_qty and increase_count == 0:
                        # Couldn't increase at all, this is the max
                        break
                    if final_qty >= desired_qty:
                        break
                except Exception:
                    pass

            except FatalBotError:
                raise  # Re-raise fatal errors immediately
            except Exception as e:
                self.logger.warning(f"Quantity read failed (attempt {attempt}): {e}")
                time.sleep(1)

        # FINAL VERIFICATION - Check maximum available quantity after all attempts
        try:
            qty_el = self.q(3).until(EC.presence_of_element_located((By.XPATH, qty_xpath)))
            final_qty = safe_get_qty(qty_el)
            
            # If final_qty is still 0 but we clicked Add successfully earlier, assume 1
            if final_qty == 0:
                 self.logger.warning("Could not read final quantity text (got 0/empty), assuming 1 since 'Add' was clicked.")
                 final_qty = 1
            
            max_available_qty = max(max_available_qty, final_qty)
            
            if final_qty >= desired_qty:
                self.logger.success(f"FINAL QUANTITY: {final_qty}/{desired_qty} - SUCCESS")
            else:
                self.logger.warning(f"FINAL QUANTITY: {final_qty}/{desired_qty} - LESS THAN DESIRED")
            
            # Only record warnings if there's an actual quantity issue
            if final_qty < desired_qty: # use final_qty instead of max_available_qty for final check
                if not self.allow_less_qty:
                    # If allow_less_qty is disabled, this is a fatal error
                    self.logger.error(f"[STOCK] Quantity {final_qty} < desired {desired_qty} and allow_less_qty is disabled - stopping all workers")
                    self._record_stock_warning(product_name, product_url, desired_qty, final_qty)
                    self._fatal("QTY_TOO_LOW")  # This will raise FatalBotError
                else:
                    # If allow_less_qty is enabled, just record a warning (not fatal)
                    self._record_stock_warning(product_name, product_url, desired_qty, final_qty)
                    self.logger.warning(f"[STOCK] Available quantity {final_qty} < desired {desired_qty} but allow_less_qty is enabled - continuing")
            # If final_qty >= desired_qty, no warning needed - quantity is sufficient
        except FatalBotError:
            raise  # Re-raise fatal errors immediately
        except Exception as e:
            # If verification REALLY fails (element gone?), don't crash if we allow less qty
            if self.allow_less_qty:
                 self.logger.warning(f"Quantity verification error: {e}. Continuing assuming successful add.")
            else:
                 self.logger.error(f"Could not verify final quantity: {e}")
                 self._fatal("QTY_VERIFICATION_FAILED")

    # ------------------------------------------------------------------
    # Add all products
    # ------------------------------------------------------------------
    def step_add_all_products(self):
        self.logger.step("ADD_PRODUCTS", "STARTED")
        self.logger.info(f"Adding {len(self.products)} product(s) to cart...")
        for idx, (url, qty) in enumerate(self.products.items(), 1):
            self.logger.info(f"\n[PRODUCT {idx}/{len(self.products)}]")
            self.step_add_single_product(url.strip(), qty)
            # If a fatal stock pending confirmation was raised, stop adding more products
            if self.fatal_error and self.fatal_code == "STOCK_PENDING_CONFIRM":
                self.logger.warning("Stock pending confirmation – pausing product addition pipeline")
                break
            # if other fatal occurred, step_add_single_product would have raised via _fatal
            time.sleep(2)
        self.logger.info("All products added, navigating to cart...")
        try:
            basket = self.q(3).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//img[contains(@src,'a0045e4c-78ec-48e8-9d93-956ed6a05d5e.png')]/parent::div")
            )
        )
            self.logger.info("Clicking basket icon...")
            self.safe_click(basket)
            self.logger.info("Basket icon clicked successfully")

        except Exception as e:
            self.logger.warning(f"Basket Icon Not Found: {e}, trying direct navigation...")
            try:
                self.driver.get("https://www.flipkart.com/viewcart?marketplace=GROCERY")
                self.logger.info("Navigated to cart page directly")
            except Exception as e2:
                self.logger.error(f"Failed to navigate to cart: {e2}")
                self._fatal("CART_NAVIGATION_FAILED")
        time.sleep(2)
        self.logger.step("ADD_PRODUCTS", "SUCCESS")

    # ------------------------------------------------------------------
    # Apply cart deals
    # ------------------------------------------------------------------
    def step_apply_cart_deals(self, target_first_word=None):
        """
        Apply cart deals by clicking Add/Apply buttons.
        Handles both 'Add' and 'Apply deal' button text (case-insensitive).
        Extracts and logs product names and prices.
        
        Args:
            target_first_word: Optional keyword to filter specific deals
        """
        target_first_word = (target_first_word or "").upper().strip()
        
        self.logger.step("APPLY_DEALS", "STARTED")
        
        # Check auto_apply_deals toggle
        if not self.auto_apply_deals:
            self.logger.info("Auto-apply deals is DISABLED - skipping deal application")
            self.logger.step("APPLY_DEALS", "SKIPPED")
            return
        
        try:
            # Wait for page to stabilize
            time.sleep(1.5)
            
            # Strategy: Find clickable button divs with orange border
            button_containers = self.driver.find_elements(
                By.XPATH,
                "//div[contains(@style, 'border-color: rgb(133, 60, 14)')]"
            )
            
            self.logger.info(f"Found {len(button_containers)} potential deal button containers")
            
            deals_found = []
            
            for idx, container in enumerate(button_containers):
                try:
                    if not container.is_displayed():
                        self.logger.info(f"[DEBUG] Container #{idx+1}: Not displayed - skipping")
                        continue
                    
                    # Log all text in this container for debugging
                    try:
                        all_container_text = container.text.strip()
                        self.logger.info(f"[DEBUG] Container #{idx+1}: Full text = '{all_container_text[:100]}...'")
                    except:
                        pass
                    
                    # Get the button text
                    text_elements = container.find_elements(
                        By.XPATH,
                        ".//div[@class='css-1rynq56']"
                    )
                    
                    self.logger.info(f"[DEBUG] Container #{idx+1}: Found {len(text_elements)} text elements with class 'css-1rynq56'")
                    
                    button_text = ""
                    for elem in text_elements:
                        text = elem.text.strip()
                        text_lower = text.lower()
                        self.logger.info(f"[DEBUG] Container #{idx+1}: Text element = '{text}'")
                        if text_lower in ['add', 'apply deal', 'apply']:
                            button_text = text
                            break
                    
                    if not button_text:
                        # Fallback: check all text in container
                        container_text = container.text.strip().lower()
                        self.logger.info(f"[DEBUG] Container #{idx+1}: No button text in elements, checking full container text")
                        if 'add' in container_text or 'apply' in container_text:
                            button_text = container.text.strip().split('\n')[0]
                            self.logger.info(f"[DEBUG] Container #{idx+1}: Found button text in full text: '{button_text}'")
                        else:
                            self.logger.info(f"[DEBUG] Container #{idx+1}: No Add/Apply button text found anywhere - skipping")
                            continue
                    
                    self.logger.info(f"[DEBUG] Container #{idx+1}: Found button text '{button_text}' - extracting product info...")
                    
                    # Extract product name and price by traversing up
                    product_name = ""
                    product_price = ""
                    original_price = ""
                    is_unlocked = False
                    
                    try:
                        # Go up to find the parent deal container
                        current = container
                        deal_container = None
                        
                        for _ in range(10):  # Increased range to find container
                            current = current.find_element(By.XPATH, "./parent::div")
                            style = current.get_attribute("style") or ""
                            
                            # The deal container has: border-radius: 4px; margin-bottom: 8px
                            if "border-radius: 4px" in style and "margin-bottom: 8px" in style:
                                deal_container = current
                                break
                        
                        if not deal_container:
                            # Try alternate approach - get the outermost parent
                            current = container
                            for _ in range(10):
                                parent = current.find_element(By.XPATH, "./parent::div")
                                class_attr = parent.get_attribute("class") or ""
                                if "css-175oi2r" in class_attr:
                                    current = parent
                                    deal_container = current
                                else:
                                    break
                        
                        if deal_container:
                            # Check for "Deal unlocked" status
                            try:
                                unlocked_elements = deal_container.find_elements(
                                    By.XPATH,
                                    ".//*[contains(text(), 'Deal unlocked') or contains(text(), 'deal unlocked')]"
                                )
                                if unlocked_elements:
                                    for elem in unlocked_elements:
                                        if elem.is_displayed() and elem.text.strip():
                                            is_unlocked = True
                                            break
                            except:
                                pass
                            
                            # Also check for green background (unlocked indicator)
                            try:
                                green_divs = deal_container.find_elements(
                                    By.XPATH,
                                    ".//div[contains(@style, 'background-color: rgb(231, 248, 236)')]"
                                )
                                if green_divs and any(d.is_displayed() for d in green_divs):
                                    is_unlocked = True
                            except:
                                pass
                            
                            # Extract product name - Multiple strategies
                            # Strategy 1: Look for specific color and font-size
                            if not product_name:
                                try:
                                    name_candidates = deal_container.find_elements(
                                        By.XPATH,
                                        ".//div[contains(@style, 'color: rgb(33, 33, 33)') and contains(@style, 'font-size: 12px')]"
                                    )
                                    for candidate in name_candidates:
                                        text = candidate.text.strip()
                                        if self._is_valid_product_name(text):
                                            product_name = text
                                            break
                                except:
                                    pass
                            
                            # Strategy 2: Look for any dark text that's not a price
                            if not product_name:
                                try:
                                    all_divs = deal_container.find_elements(By.TAG_NAME, "div")
                                    for div in all_divs:
                                        text = div.text.strip()
                                        if self._is_valid_product_name(text):
                                            product_name = text
                                            break
                                except:
                                    pass
                            
                            # Strategy 3: Get all text and parse
                            if not product_name:
                                try:
                                    full_text = deal_container.text
                                    lines = [line.strip() for line in full_text.split('\n') if line.strip()]
                                    for line in lines:
                                        if self._is_valid_product_name(line):
                                            product_name = line
                                            break
                                except:
                                    pass
                            
                            # Extract price - Look for ₹ symbol with font-size: 17px
                            try:
                                price_elements = deal_container.find_elements(
                                    By.XPATH,
                                    ".//div[contains(@style, 'font-size: 17px') and contains(text(), '₹')]"
                                )
                                if price_elements:
                                    for elem in price_elements:
                                        text = elem.text.strip()
                                        if text.startswith('₹'):
                                            product_price = text
                                            break
                            except:
                                pass
                            
                            # Extract original price (strikethrough)
                            try:
                                original_price_elements = deal_container.find_elements(
                                    By.XPATH,
                                    ".//div[contains(@style, 'text-decoration-line: line-through') and contains(text(), '₹')]"
                                )
                                if original_price_elements:
                                    for elem in original_price_elements:
                                        text = elem.text.strip()
                                        if text.startswith('₹'):
                                            original_price = text
                                            break
                            except:
                                pass
                        else:
                            self.logger.info(f"[DEBUG] Container #{idx+1}: Could not find deal container parent")
                    
                    except Exception as e:
                        self.logger.info(f"[DEBUG] Container #{idx+1}: Error traversing to parent container: {e}")
                    
                    # Extract first word for filtering
                    first_word = product_name.split()[0].upper() if product_name else ""
                    
                    # Format price display
                    price_display = product_price
                    if product_price and original_price:
                        price_display = f"{product_price} (was {original_price})"
                    elif not product_price:
                        price_display = "Price not found"
                    
                    # Log what we extracted
                    self.logger.info(f"[DEBUG] Container #{idx+1}: Extracted - Name: '{product_name or 'Unknown'}', Price: '{product_price or 'N/A'}', Unlocked: {is_unlocked}")
                    
                    # Add to deals_found even if some data is missing
                    deals_found.append({
                        "element": container,
                        "button_text": button_text,
                        "product_name": product_name or "Unknown Product",
                        "product_price": product_price,
                        "original_price": original_price,
                        "price_display": price_display,
                        "first_word": first_word,
                        "is_unlocked": is_unlocked
                    })
                    
                except Exception as e:
                    self.logger.info(f"[DEBUG] Container #{idx+1}: Error processing container: {e}")
                    continue
            
            # Log all found deals
            self.logger.info(f"Found {len(deals_found)} clickable deal button(s)")
            for idx, deal in enumerate(deals_found):
                status = "UNLOCKED" if deal["is_unlocked"] else "AVAILABLE"
                self.logger.info(f"  Deal #{idx+1}: '{deal['product_name']}' - {deal['price_display']} - Button: '{deal['button_text']}' [{status}]")
            
            if not deals_found:
                self.logger.warning("No Add/Apply buttons found")
                self.logger.step("APPLY_DEALS", "SKIPPED")
                return
            
            # Determine which deals to click based on new logic
            deals_to_click = []
            
            # Find all ₹1 products
            one_rupee_deals = [d for d in deals_found if d['product_price'] == '₹1']
            
            if target_first_word:
                # User specified a keyword - search for it first
                self.logger.info(f"Searching for keyword: '{target_first_word}'")
                matching_deals = [d for d in deals_found if d["first_word"] == target_first_word]
                
                if matching_deals:
                    # Check if keyword match is unlocked
                    unlocked_matches = [d for d in matching_deals if d['is_unlocked']]
                    
                    if unlocked_matches:
                        self.logger.success(f"Found UNLOCKED deal matching '{target_first_word}' - clicking it")
                        deals_to_click = unlocked_matches[:1]  # Click only the first unlocked match
                    else:
                        # Keyword found but not unlocked - fallback to ₹1 product
                        self.logger.warning(f"Found '{target_first_word}' but it's NOT UNLOCKED")
                        if one_rupee_deals:
                            self.logger.info(f"Falling back to ₹1 product instead")
                            deals_to_click = one_rupee_deals[:1]  # Click only first ₹1 product
                        else:
                            self.logger.warning("No ₹1 product available - skipping deals")
                            deals_to_click = []
                else:
                    # Keyword not found - fallback to ₹1 product
                    self.logger.warning(f"Keyword '{target_first_word}' NOT FOUND in available deals")
                    if one_rupee_deals:
                        self.logger.info(f"Falling back to ₹1 product instead")
                        deals_to_click = one_rupee_deals[:1]  # Click only first ₹1 product
                    else:
                        self.logger.warning("No ₹1 product available - skipping deals")
                        deals_to_click = []
            else:
                # No keyword specified - only click if ₹1 product exists
                if one_rupee_deals:
                    self.logger.info(f"Found {len(one_rupee_deals)} ₹1 product(s) - clicking first one")
                    deals_to_click = one_rupee_deals[:1]  # Click only first ₹1 product
                else:
                    self.logger.warning("No ₹1 product found - skipping all deals")
                    deals_to_click = []
            
            # Click selected deals
            clicked_count = 0
            clicked_products = []
            
            if not deals_to_click:
                self.logger.info("No deals selected to click - moving forward")
                self.logger.step("APPLY_DEALS", "SKIPPED")
                return
            
            for deal in deals_to_click:
                try:
                    product = deal['product_name']
                    price = deal['price_display']
                    button_text = deal['button_text']
                    
                    self.logger.info(f"Clicking '{button_text}' for: {product} - {price}")
                    
                    # Scroll into view
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", deal['element'])
                    time.sleep(0.3)
                    
                    # Click using JavaScript for reliability
                    self.driver.execute_script("arguments[0].click();", deal['element'])
                    
                    clicked_count += 1
                    clicked_products.append(f"{product} - {price}")
                    self.logger.success(f"✓ Deal added: {product} - {price}")
                    
                    # Short delay between clicks
                    time.sleep(0.8)
                    
                except Exception as e:
                    self.logger.warning(f"Failed to click deal for '{deal['product_name']}': {e}")
                    continue
            
            # Final summary
            if clicked_count > 0:
                self.logger.success(f"Successfully applied {clicked_count} deal(s):")
                for product in clicked_products:
                    self.logger.success(f"  • {product}")
                self.logger.step("APPLY_DEALS", "SUCCESS")
            else:
                self.logger.error("Failed to apply any deals")
                self.logger.step("APPLY_DEALS", "FAILED")
        
        except Exception as e:
            self.logger.error(f"Error in step_apply_cart_deals: {e}")
            self.logger.step("APPLY_DEALS", "ERROR")
            raise


    def _is_valid_product_name(self, text):
        """
        Helper function to validate if text is a valid product name.
        
        Args:
            text: Text to validate
            
        Returns:
            bool: True if text appears to be a valid product name
        """
        if not text or len(text) < 4:
            return False
        
        # Exclude common non-product text
        text_lower = text.lower()
        excluded_phrases = [
            'deal unlocked', 'unlocked', 'add', 'apply', 'apply deal',
            'save', 'off', 'discount', 'free delivery', 'delivery',
            'kg', 'g', 'ml', 'l', 'litre', 'liter', 'gram', 'pack'
        ]
        
        # Check if text is just a measurement or excluded phrase
        if text_lower in excluded_phrases:
            return False
        
        # Check if text starts with ₹ (price)
        if text.startswith('₹'):
            return False
        
        # Check if text is mostly numbers
        digits = sum(c.isdigit() for c in text)
        if digits > len(text) / 2:
            return False
        
        # Must have at least some alphabetic characters
        if not any(c.isalpha() for c in text):
            return False
        
        return True

    # ------------------------------------------------------------------
    # Apply coupon
    # ------------------------------------------------------------------
    def step_apply_coupon(self, use_coupon=True):
        self.logger.step("APPLY_COUPON", "STARTED")
        self.logger.info(f"use_coupon={use_coupon}, coupon='{self.coupon}'")
        
        if not use_coupon:
            self.logger.info("SKIPPING - use_coupon is False")
            self.logger.step("APPLY_COUPON", "SKIPPED")
            return

        if not self.coupon or self.coupon in ("", "None", None):
            self.logger.warning("SKIPPING - No coupon code provided")
            self.logger.step("APPLY_COUPON", "SKIPPED")
            return
        
        self.logger.info(f"PROCEEDING - use_coupon={use_coupon}, coupon='{self.coupon}'")
        self.logger.info("Starting coupon apply process...")
        
        # -------------------------------------------------------------
        # FIRST: CHECK FOR DIRECT APPLY BUTTON (before opening coupon section)
        # -------------------------------------------------------------
        self.logger.info("Checking for direct Apply button...")
        try:
            # Try multiple XPath patterns to find Apply button
            apply_buttons = self.driver.find_elements(By.XPATH, 
                "//div[normalize-space(text())='Apply' or text()='Apply']"
            )
            
            for apply_btn in apply_buttons:
                try:
                    # Check if it's visible and has the right color/style
                    if apply_btn.is_displayed():
                        style = apply_btn.get_attribute("style") or ""
                        classes = apply_btn.get_attribute("class") or ""
                        
                        # Check for the orange/brown color (rgb(157, 73, 0) or similar)
                        if "rgb(157, 73, 0)" in style or "rgb(133, 60, 14)" in style or "157, 73, 0" in style:
                            self.logger.success("Found direct Apply button → clicking it and skipping coupon entry")
                            self.safe_click(apply_btn)
                            self.apply_button_used = True
                            time.sleep(2)
                            
                            # Check for errors
                            try:
                                coupon_error = self.driver.find_element(
                                    By.XPATH,
                                    "//div[contains(text(),'max usage') or contains(text(),'Invalid coupon') or contains(text(),'Maximum usage limit')]"
                                )
                                if coupon_error.is_displayed():
                                    msg = coupon_error.text.strip()
                                    self.logger.error(f"COUPON ERROR: {msg}")
                                    if "max usage" in msg.lower() or "maximum usage" in msg.lower():
                                        self._fatal("COUPON_MAX_USAGE_LIMIT")
                                    else:
                                        self._fatal("INVALID_COUPON")
                            except NoSuchElementException:
                                self.logger.success("Apply button clicked successfully - no errors detected")
                            
                            self.logger.step("APPLY_COUPON", "SUCCESS")
                            return  # Exit early, coupon applied
                except Exception as e:
                    continue
            
            self.logger.info("No direct Apply button found, proceeding to open coupon section...")
        except FatalBotError:
            raise  # Re-raise fatal errors immediately
        except Exception as e:
            self.logger.warning(f"Error checking for Apply button: {e}, proceeding to open coupon section...")
        
        opener = None
        time.sleep(0.5)

        # -------------------------------------------------------------
        # OPEN COUPON SECTION (only if Apply button not found)
        # -------------------------------------------------------------
        try:
            opener = self.q(4).until(EC.any_of(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//div[normalize-space(text())='View all' and contains(@style,'rgb(17, 98, 242)')]"
                )),
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//div[contains(text(),'View all') and contains(@style,'rgb(17, 98, 242)')]"
                )),
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//div[normalize-space(text())='Add Coupon' and contains(@style,'rgb(17, 98, 242)')]"
                )),
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//span[normalize-space(text())='Add Coupon']/parent::div[contains(@style,'rgb(17, 98, 242)')]"
                )),
            ))


            self.safe_click(opener)
            self.logger.info(f"Coupon section opened via: '{opener.text}'")
            time.sleep(1)
        except FatalBotError:
            raise  # Re-raise fatal errors immediately
        except Exception:
            time.sleep(1.5)
            try:
                opener = self.q(3).until(
                    EC.element_to_be_clickable((By.XPATH, "//div[contains(text(),'Coupon')]"))
                )
                self.safe_click(opener)
                time.sleep(1)
            except Exception:
                self._fatal("VIEWALL_BUTTON_NOT_FOUND")
                self.logger.warning("Coupon section not available — skipping")
                opener = None

        # -------------------------------------------------------------
        # CHECK FOR APPLY BUTTON AFTER OPENING COUPON SECTION
        # If Apply button exists, it means a coupon is pre-selected - just click it!
        # -------------------------------------------------------------
        apply_button_found_after_open = False
        apply_button_element = None
        if opener:
            self.logger.info("Checking for Apply button after opening coupon section...")
            try:
                # Try multiple patterns for Apply button
                apply_buttons = self.driver.find_elements(By.XPATH,
                    "//div[normalize-space(text())='Apply' or text()='Apply']"
                )
                
                for apply_btn in apply_buttons:
                    try:
                        if apply_btn.is_displayed():
                            style = apply_btn.get_attribute("style") or ""
                            # Check for orange/brown color
                            if "rgb(157, 73, 0)" in style or "rgb(133, 60, 14)" in style or "157, 73, 0" in style:
                                self.logger.success("Found Apply button after opening section → clicking it directly (coupon pre-selected)")
                                apply_button_found_after_open = True
                                apply_button_element = apply_btn
                                break
                    except FatalBotError:
                        raise  # Re-raise fatal errors immediately
                    except Exception:
                        continue

                    # Detect ANY coupon error (max usage, invalid)
                    try:
                        coupon_error = self.driver.find_element(
                            By.XPATH,
                            "//div[contains(@class,'css-1rynq56') and (contains(text(),'max usage') or contains(text(),'Invalid coupon'))]"
                        )
                        if coupon_error.is_displayed():
                            msg = coupon_error.text.strip()
                            self.logger.error(f"COUPON ERROR DETECTED → {msg}")
                            if "max usage" in msg.lower():
                                self._fatal("COUPON_MAX_USAGE_LIMIT")
                            else:
                                self._fatal("INVALID_COUPON")
                    except FatalBotError:
                        raise  # Re-raise fatal errors immediately
                    except NoSuchElementException:
                        pass
            except FatalBotError:
                raise  # Re-raise fatal errors immediately
            except NoSuchElementException:
                pass

        # -------------------------------------------------------------
        # IF APPLY BUTTON FOUND: Click it immediately and exit
        # Otherwise: Enter coupon manually
        # -------------------------------------------------------------
        if apply_button_found_after_open and apply_button_element:
            # Apply button exists - coupon is pre-selected, just click it!
            try:
                self.logger.info("Clicking pre-selected coupon Apply button...")
                self.safe_click(apply_button_element)
                self.apply_button_used = True
                self.logger.success("APPLY BUTTON CLICKED — COUPON APPLIED!")
                time.sleep(2)

                # Check for errors after clicking - look for RED error text, not just any text
                try:
                    # Find all divs with the common class that might contain errors or buttons
                    potential_errors = self.driver.find_elements(
                        By.XPATH,
                        "//div[contains(@class,'css-1rynq56')]"
                    )
                    
                    actual_error = None
                    for elem in potential_errors:
                        try:
                            if elem.is_displayed():
                                text = elem.text.strip().lower()
                                style = elem.get_attribute("style") or ""
                                
                                # Check if this is an ERROR by checking for:
                                # 1. Red color (rgb(198, 4, 36) or similar red colors)
                                # 2. Error-related text
                                is_red = "rgb(198, 4, 36)" in style or "rgb(248, 81, 73)" in style or "rgb(255, 0, 0)" in style
                                has_error_text = any(keyword in text for keyword in ['invalid', 'expired', 'max usage', 'maximum usage', 'not applicable', 'not valid', 'error'])
                                
                                # Only treat as error if BOTH red color AND error text are present
                                if is_red and has_error_text:
                                    actual_error = elem
                                    break
                        except:
                            continue
                    
                    if actual_error:
                        msg = actual_error.text.strip()
                        self.logger.error(f"COUPON ERROR: {msg}")
                        if "max usage" in msg.lower() or "maximum usage" in msg.lower():
                            self._fatal("COUPON_MAX_USAGE_LIMIT")
                        else:
                            self._fatal("INVALID_COUPON")
                    else:
                        self.logger.success("Apply button clicked successfully - no errors detected")
                        
                except NoSuchElementException:
                    self.logger.success("Apply button clicked successfully - no errors detected")
                
                self.logger.step("APPLY_COUPON", "SUCCESS")
                try:
                    btn = self.driver.find_element(By.XPATH, "//a[contains(@class,'jlLn4z')]")
                    self.driver.execute_script("arguments[0].click();", btn)
                except Exception as e:
                    self._fatal("BACK_ICON_NOT_FOUND")
                        
                return  # Exit early - coupon applied successfully
            except FatalBotError:
                raise
            except Exception as e:
                self.logger.warning(f"Failed to click pre-selected Apply button: {e}, will try manual entry...")
                # Fall through to manual entry
        
        # -------------------------------------------------------------
        # ENTER COUPON MANUALLY (only if no Apply button was found/clicked)
        # -------------------------------------------------------------
        if opener:
            try:
                coupon_input = self.q(5).until(EC.presence_of_element_located((
                    By.XPATH, "//input[@placeholder='Enter coupon code' or contains(@placeholder,'coupon')]"
                )))
                self.logger.info(f"Entering coupon code: {self.coupon}")
                self.clear_and_send(coupon_input, self.coupon)
                self.logger.info("Coupon code entered")
                self.coupon_filled = True

                # Find Apply button
                self.logger.info("Finding and clicking Apply button...")
                apply_btn = self.q(5).until(EC.any_of(
                    EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'css-1rynq56') and normalize-space(text())='Add Coupon']")),
                    EC.element_to_be_clickable((By.XPATH, "//div[text()='Apply']")),
                ))
                self.safe_click(apply_btn)
                
                self.logger.success("APPLY BUTTON CLICKED — COUPON APPLIED!")
                time.sleep(2)

                # Detect coupon errors - look for RED error text, not just any text
                try:
                    # Find all divs with the common class
                    potential_errors = self.driver.find_elements(
                        By.XPATH,
                        "//div[contains(@class,'css-1rynq56')]"
                    )
                    
                    actual_error = None
                    for elem in potential_errors:
                        try:
                            if elem.is_displayed():
                                text = elem.text.strip().lower()
                                style = elem.get_attribute("style") or ""
                                
                                # Check if this is an ERROR by checking for:
                                # 1. Red color (rgb(198, 4, 36) or similar red colors)
                                # 2. Error-related text
                                is_red = "rgb(198, 4, 36)" in style or "rgb(248, 81, 73)" in style or "rgb(255, 0, 0)" in style
                                has_error_text = any(keyword in text for keyword in ['invalid', 'expired', 'max usage', 'maximum usage', 'not applicable', 'not valid', 'error'])
                                
                                # Only treat as error if BOTH red color AND error text are present
                                if is_red and has_error_text:
                                    actual_error = elem
                                    break
                        except:
                            continue
                    
                    if actual_error:
                        msg = actual_error.text.strip()
                        msg_l = msg.lower()
                        self.logger.error(f"COUPON ERROR DETECTED → {msg}")
                        if "max usage" in msg_l or "usage limit" in msg_l:
                            self._fatal("COUPON_MAX_USAGE_LIMIT")
                        elif "expired" in msg_l:
                            self._fatal("COUPON_EXPIRED")
                        else:
                            self._fatal("INVALID_COUPON")
                except Exception:
                    # No coupon error found (or couldn't read it) -> continue
                    pass
                
                # If a fatal coupon error happened above, don't mark success or continue
                if self.fatal_error:
                    return

                self.logger.step("APPLY_COUPON", "SUCCESS")

            except FatalBotError:
                # re-raise fatal so outer run() can catch and return code
                raise
            except Exception as e:
                self.logger.error(f"Coupon apply failed: {e}")
                self._fatal("COUPON_APPLY_ERROR")

            # If coupon step is already fatal, don't try to click back icon
            if self.fatal_error:
                return

            try:
                btn = self.driver.find_element(By.XPATH, "//a[contains(@class,'jlLn4z')]")
                self.driver.execute_script("arguments[0].click();", btn)
            except Exception as e:
                self._fatal("BACK_ICON_NOT_FOUND")
                                            

    # ------------------------------------------------------------------
    # Checkout & order
    # ------------------------------------------------------------------
    def step_checkout(self):
        # If a fatal error already occurred, don't start checkout
        if self.fatal_error:
            return

        # Check driver health BEFORE logging step start, so we don't show CHECKOUT if driver is dead
        if not self._check_driver_health():
            self._fatal("DRIVER_UNRESPONSIVE")
            return

        self.logger.step("CHECKOUT", "STARTED")

        # BACK TO CART (conditional)
        if self.apply_button_used:
            self.logger.info("Skipping back to cart (Apply button already used).")
        elif self.coupon_filled:
            try:
                back = self.q(4).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[@class='_3NH1qf']"))
                )
                self.safe_click(back)
                self.logger.info("Back to cart clicked (coupon filled manually)")
            except FatalBotError:
                raise  # Re-raise fatal errors immediately
            except Exception:
                self.logger.warning("Back icon not found (might already be on cart page)")
        else:
            self.logger.info("Skipping back to cart (no coupon filled).")

        # CONTINUE / PLACE ORDER - Multiple fallback XPaths
        try:
            # Scroll to ensure button is visible
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            
            continue_xpaths = [
                "(//div[contains(@class,'r-eu3ka') and .//div[normalize-space(.)='Continue' or normalize-space(.)='Place Order']])[last()]",
                "//div[contains(@class,'r-eu3ka')]//div[normalize-space(.)='Continue']",
                "//div[normalize-space(.)='Continue' and contains(@class,'r-eu3ka')]",
                "//button[normalize-space(.)='Continue']",
                "//div[normalize-space(.)='Place Order']"
            ]
            
            continue_btn = self.find_clickable_with_retry(continue_xpaths, timeout=5, retries=1, error_code="CHECKOUT_CONTINUE_FAILED")
            
            self.safe_click(continue_btn)
            self.logger.info("CONTINUE clicked")
            time.sleep(2)
        except FatalBotError:
            raise  # Re-raise fatal errors immediately
        except Exception as e:
            self.logger.error(f"Continue error: {e}")
            self._fatal("CHECKOUT_CONTINUE_FAILED")

        #PRICE VALIDATION CHECK
        # PRICE VALIDATION
        try:
            price_xpath = (
                "//div[normalize-space(text())='Total Amount']"
                "/following::div[contains(normalize-space(text()), '₹')][1]"
            )

            self.q(12).until(
                EC.visibility_of_element_located((By.XPATH, price_xpath))
            )

            price_text = self.driver.find_element(By.XPATH, price_xpath).text.strip()

            digits = "".join(filter(str.isdigit, price_text))
            if not digits:
                self._fatal("PRICE_NOT_FOUND")

            numeric_price = int(digits)

            self.logger.info(
                f"Price validation: {numeric_price} (max: {self.max_price})"
            )

            if numeric_price > self.max_price:
                self._fatal("PRICE_TOO_HIGH")

        except FatalBotError:
            raise  # Re-raise fatal errors immediately
        except Exception as e:
            self.logger.error(f"Price validation error: {e}")
            self._fatal("PRICE_VALIDATION_ERROR")


        # SECOND CONTINUE BUTTON
        try:
            # Scroll to ensure button is visible
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            
            # Target the outer clickable div with r-eu3ka class that contains Continue text
            second_continue_xpaths = [
                "(//div[contains(@class,'r-eu3ka') and .//div[normalize-space(.)='Continue']])[last()]",
                "//div[contains(@class,'r-eu3ka')][.//div[normalize-space(text())='Continue']]",
                "//div[contains(@class,'r-eu3ka') and contains(@class,'r-1awozwy')][.//div[contains(text(),'Continue')]]",
                "//div[.//div[normalize-space(text())='Continue']][contains(@class,'r-eu3ka')]",
                "//button[normalize-space(.)='Continue']",
                "//div[normalize-space(.)='Continue' and contains(@class,'r-eu3ka')]"
            ]
            
            # Find the element
            second_continue_btn = self.find_clickable_with_retry(second_continue_xpaths, timeout=5, retries=1, error_code="SECOND_CONTINUE_FAILED")
            
            # Ensure we have the outer clickable div, not the inner text div
            element_class = second_continue_btn.get_attribute('class') or ''
            if 'r-eu3ka' not in element_class:
                # We might have found the inner div, try to get the parent
                try:
                    parent = second_continue_btn.find_element(By.XPATH, "./..")
                    parent_class = parent.get_attribute('class') or ''
                    if 'r-eu3ka' in parent_class:
                        second_continue_btn = parent
                        self.logger.info("Using parent element with r-eu3ka class")
                except Exception:
                    pass
            
            # Wait a bit and verify element is still clickable
            time.sleep(0.3)
            if not (second_continue_btn.is_displayed() and second_continue_btn.is_enabled()):
                # Re-find if stale
                second_continue_btn = self.find_clickable_with_retry(second_continue_xpaths, timeout=3, retries=1, error_code="SECOND_CONTINUE_FAILED")
                # Check parent again
                element_class = second_continue_btn.get_attribute('class') or ''
                if 'r-eu3ka' not in element_class:
                    try:
                        parent = second_continue_btn.find_element(By.XPATH, "./..")
                        parent_class = parent.get_attribute('class') or ''
                        if 'r-eu3ka' in parent_class:
                            second_continue_btn = parent
                    except Exception:
                        pass
            
            # Scroll into view
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center', behavior:'smooth'});", second_continue_btn)
            time.sleep(0.5)
            
            # Log the element we're about to click
            final_class = second_continue_btn.get_attribute('class') or ''
            self.logger.info(f"Clicking element with classes: {final_class[:100]}")
            
            # Try multiple click strategies
            clicked = False
            try:
                # Strategy 1: JavaScript click on the element
                self.driver.execute_script("arguments[0].click();", second_continue_btn)
                clicked = True
                self.logger.info("Second Continue clicked (JS click)")
            except Exception as e1:
                try:
                    # Strategy 2: Regular click
                    second_continue_btn.click()
                    clicked = True
                    self.logger.info("Second Continue clicked (regular click)")
                except Exception as e2:
                    try:
                        # Strategy 3: Click via parent if needed
                        parent = second_continue_btn.find_element(By.XPATH, "./..")
                        if 'r-eu3ka' in parent.get_attribute('class'):
                            self.driver.execute_script("arguments[0].click();", parent)
                            clicked = True
                            self.logger.info("Second Continue clicked (via parent)")
                    except Exception as e3:
                        self.logger.warning(f"All click strategies failed: JS={e1}, Regular={e2}, Parent={e3}")
            
            if not clicked:
                self.logger.error("Failed to click second continue button")
                self._fatal("SECOND_CONTINUE_CLICK_FAILED")
            
            time.sleep(2)

        except FatalBotError:
            raise
        except Exception as e:
            self.logger.info(f"No second continue (might not be needed): {e}")


        # COD - Multiple fallback XPaths
        try:
            cod_xpaths = [
                "//span[normalize-space(.)='Cash on Delivery']",
                "//span[contains(text(),'Cash on Delivery')]",
                "//div[normalize-space(.)='Cash on Delivery']",
                "//label[contains(.,'Cash on Delivery')]",
                "//input[@value='COD' or @type='radio' and following-sibling::span[contains(text(),'Cash')]]"
            ]
            
            cod_option = self.find_clickable_with_retry(cod_xpaths, timeout=5, retries=1, error_code="COD_SELECTION_FAILED")
            
            self.safe_click(cod_option)
            self.logger.info("COD selected")
            time.sleep(2)
        except FatalBotError:
            raise  # Re-raise fatal errors immediately
        except Exception as e:
            self.logger.error(f"COD selection error: {e}")
            self._fatal("COD_SELECTION_FAILED")

        # PLACE ORDER - Multiple fallback XPaths
        try:
            # Scroll to bottom to ensure button is visible
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            
            place_order_xpaths = [
                "//button[@id='cod-place-order' and @data-testid='payButton']",
                "//button[@data-testid='payButton']",
                "//button[contains(@class,'payButton')]",
                "//button[contains(text(),'Place Order') or contains(text(),'PLACE ORDER')]",
                "//div[contains(@class,'payButton')]//button",
                "//button[@id='cod-place-order']"
            ]
            
            place_order = self.find_clickable_with_retry(place_order_xpaths, timeout=5, retries=1, error_code="PLACE_ORDER_FAILED")
            
            self.safe_click(place_order)
            self.logger.info("Place Order clicked")
            time.sleep(2)
        except FatalBotError:
            raise  # Re-raise fatal errors immediately
        except Exception as e:
            self.logger.error(f"Place Order error: {e}")
            self._fatal("PLACE_ORDER_FAILED")

        # CONFIRM ORDER - Multiple fallback XPaths
        try:
            # Wait a bit for confirm button to appear
            time.sleep(1)
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            
            confirm_xpaths = [
                "//button[contains(@class,'Button-module_button') and normalize-space(.)='Confirm order']",
                "//button[normalize-space(.)='Confirm order' or normalize-space(.)='Confirm Order']",
                "//button[contains(text(),'Confirm')]",
                "//div[normalize-space(.)='Confirm order']//parent::button",
                "//button[@data-testid='confirm-order']"
            ]
            
            confirm_btn = self.find_clickable_with_retry(confirm_xpaths, timeout=6, retries=1, error_code="CONFIRM_ORDER_FAILED")
            
            self.safe_click(confirm_btn)
            self.logger.info("Confirm order clicked")
            time.sleep(2)
        except FatalBotError:
            raise  # Re-raise fatal errors immediately
        except Exception as e:
            self.logger.error(f"Confirm order error: {e}")
            self._fatal("CONFIRM_ORDER_FAILED")
        time.sleep(2)
        # EXTRACT ORDER ID
        try:
            self.driver.get("https://www.flipkart.com/rv/orders?isSkipOc=true")
            time.sleep(2)
            
            # Check if orders page is open (mark as success even if order ID extraction fails)
            current_url = self.driver.current_url
            orders_page_open = "flipkart.com/rv/orders" in current_url or "flipkart.com/rv/orders?isSkipOc=true" in current_url
            
            # Click delivery date - Multiple robust strategies
            try:
                # Wait for orders page to load
                time.sleep(1)
                
                # Multiple XPath and CSS selector fallbacks
                delivery_xpaths = [
                    # Target the outer clickable div with class U6seEY
                    "//div[contains(@class,'U6seEY')]",
                    # Target div containing delivery text span
                    "//div[contains(@class,'Ck4P40')]/ancestor::div[contains(@class,'U6seEY')]",
                    # Find by delivery text span and get parent clickable div
                    "//span[contains(@class,'_osffw')]/ancestor::div[contains(@class,'U6seEY')]",
                    # Alternative: find by the right chevron image and get parent
                    "//img[contains(@class,'lQTgKD')]/ancestor::div[contains(@class,'U6seEY')]",
                    # Find by structure: div with U6seEY that contains Ck4P40
                    "//div[contains(@class,'U6seEY')][.//div[contains(@class,'Ck4P40')]]",
                    # Fallback: any div with U6seEY class
                    "(//div[contains(@class,'U6seEY')])[1]"
                ]
                
                delivery_css_selectors = [
                    "div.U6seEY",
                    "div[class*='U6seEY']",
                    "div.Ck4P40",
                    "span._osffw"
                ]
                
                delivery_element = None
                
                # Try XPath selectors first
                for xpath in delivery_xpaths:
                    try:
                        elements = self.driver.find_elements(By.XPATH, xpath)
                        for el in elements:
                            if el.is_displayed() and el.is_enabled():
                                # Verify it contains delivery-related content
                                try:
                                    text = el.text.lower()
                                    class_attr = el.get_attribute('class') or ''
                                    if 'U6seEY' in class_attr or 'arriving' in text or 'delivery' in text or 'tomorrow' in text or 'today' in text:
                                        delivery_element = el
                                        self.logger.info(f"Found delivery element via XPath: {xpath[:50]}")
                                        break
                                except Exception:
                                    if 'U6seEY' in class_attr:
                                        delivery_element = el
                                        break
                        if delivery_element:
                            break
                    except Exception:
                        continue
                
                # If XPath didn't work, try CSS selectors
                if not delivery_element:
                    for css_selector in delivery_css_selectors:
                        try:
                            elements = self.driver.find_elements(By.CSS_SELECTOR, css_selector)
                            for el in elements:
                                if el.is_displayed() and el.is_enabled():
                                    class_attr = el.get_attribute('class') or ''
                                    # If it's the span, get the parent U6seEY div
                                    if '_osffw' in class_attr or 'Ck4P40' in class_attr:
                                        try:
                                            parent = el.find_element(By.XPATH, "./ancestor::div[contains(@class,'U6seEY')]")
                                            if parent.is_displayed() and parent.is_enabled():
                                                delivery_element = parent
                                                self.logger.info(f"Found delivery element via CSS (parent): {css_selector}")
                                                break
                                        except Exception:
                                            pass
                                    elif 'U6seEY' in class_attr:
                                        delivery_element = el
                                        self.logger.info(f"Found delivery element via CSS: {css_selector}")
                                        break
                            if delivery_element:
                                break
                        except Exception:
                            continue
                
                if delivery_element:
                    # Scroll into view
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center', behavior:'smooth'});", delivery_element)
                    time.sleep(0.5)
                    
                    # Try multiple click strategies
                    clicked = False
                    try:
                        # Strategy 1: JavaScript click
                        self.driver.execute_script("arguments[0].click();", delivery_element)
                        clicked = True
                        self.logger.info("Delivery date clicked (JS click)")
                    except Exception as e1:
                        try:
                            # Strategy 2: Regular click
                            delivery_element.click()
                            clicked = True
                            self.logger.info("Delivery date clicked (regular click)")
                        except Exception as e2:
                            try:
                                # Strategy 3: Click on the delivery text span inside
                                inner_span = delivery_element.find_element(By.CSS_SELECTOR, "span._osffw")
                                self.driver.execute_script("arguments[0].click();", inner_span)
                                clicked = True
                                self.logger.info("Delivery date clicked (via inner span)")
                            except Exception as e3:
                                try:
                                    # Strategy 4: Click on the right chevron
                                    chevron = delivery_element.find_element(By.CSS_SELECTOR, "img.lQTgKD")
                                    self.driver.execute_script("arguments[0].click();", chevron)
                                    clicked = True
                                    self.logger.info("Delivery date clicked (via chevron)")
                                except Exception as e4:
                                    self.logger.warning(f"All click strategies failed: JS={e1}, Regular={e2}, Span={e3}, Chevron={e4}")
                    
                    if clicked:
                        time.sleep(2)
                    else:
                        self.logger.warning("Could not click delivery date element")
                else:
                    self.logger.warning("Delivery date element not found")
                    
            except Exception as e:
                self.logger.warning(f"Could not click delivery date: {e}")

            order_id_xpaths = [
                "//div[contains(text(),'Order ID - OD')]",
                "//div[contains(text(),'Order ID')]",
                "//span[contains(text(),'Order ID')]",
                "//div[contains(@class,'order') and contains(text(),'OD')]"
            ]
            
            try:
                order_div = self.find_element_with_retry(order_id_xpaths, timeout=6, retries=1, error_code="ORDER_ID_EXTRACTION_FAILED")
                
                self.order_id = order_div.text.replace("Order ID - ", "").replace("Order ID", "").strip()
                if not self.order_id or not self.order_id.startswith("OD"):
                    self.logger.error(f"Invalid order ID extracted: {self.order_id}")
                    # If orders page is open, mark as success anyway
                    if orders_page_open:
                        self.logger.warning("Orders page is open but order ID extraction failed. Marking as success.")
                        self.order_id = "OD_SUCCESS_ORDERS_PAGE_OPEN"
                    else:
                        self._fatal("ORDER_ID_EXTRACTION_FAILED")
                
                self.logger.success(f"ORDER ID: {self.order_id}")
                
            except FatalBotError as fe:
                # If orders page is open, mark as success even if order ID extraction failed
                if orders_page_open and "ORDER_ID_EXTRACTION_FAILED" in str(fe):
                    self.logger.warning("Orders page is open but order ID extraction failed. Marking as success.")
                    self.order_id = "OD_SUCCESS_ORDERS_PAGE_OPEN"
                else:
                    raise  # Re-raise other fatal errors
            
            # Take screenshot after order ID extraction (or if orders page is open)
            if self.order_id and (self.order_id.startswith("OD") or self.order_id == "OD_SUCCESS_ORDERS_PAGE_OPEN"):
                try:
                    timestamp = int(time.time())
                    screenshot_filename = f"order_{self.order_id}_{timestamp}.png"
                    screenshot_path = os.path.join(self.screenshots_dir, screenshot_filename)
                    self.driver.save_screenshot(screenshot_path)
                    self.logger.log(f"Screenshot saved: {screenshot_path}", "SUCCESS")
                    # Generate HTTP URL for local Flask server (like imgbb but local)
                    base = self.screenshot_base_url.rstrip("/")
                    self.screenshot_url = f"{base}/{screenshot_filename}"
                    self.logger.log(f"Screenshot URL: {self.screenshot_url}", "SUCCESS")
                except Exception as e:
                    self.logger.error(f"Could not capture screenshot: {e}")
                    self.screenshot_url = "NONE"
            
            self.logger.step("CHECKOUT", "SUCCESS")
        except FatalBotError:
            raise  # Re-raise fatal errors immediately
        except Exception as e:
            self.logger.error(f"Order ID extraction error: {e}")
            # Check if orders page is open
            try:
                current_url = self.driver.current_url
                orders_page_open = "flipkart.com/rv/orders" in current_url or "flipkart.com/rv/orders?isSkipOc=true" in current_url
                if orders_page_open:
                    self.logger.warning("Orders page is open but order ID extraction failed. Marking as success.")
                    self.order_id = "OD_SUCCESS_ORDERS_PAGE_OPEN"
                    
                    # Take screenshot even if order ID extraction failed
                    try:
                        timestamp = int(time.time())
                        screenshot_filename = f"order_{self.order_id}_{timestamp}.png"
                        screenshot_path = os.path.join(self.screenshots_dir, screenshot_filename)
                        self.driver.save_screenshot(screenshot_path)
                        self.logger.log(f"Screenshot saved: {screenshot_path}", "SUCCESS")
                        # Public/local URL (expects a static server at SCREENSHOT_BASE_URL)
                        base = self.screenshot_base_url.rstrip("/")
                        self.screenshot_url = f"{base}/{screenshot_filename}"
                        self.logger.log(f"Screenshot URL (local HTTP): {self.screenshot_url}", "SUCCESS")
                    except Exception as screenshot_error:
                        self.logger.error(f"Could not capture screenshot: {screenshot_error}")
                        self.screenshot_url = "NONE"
                    
                    self.logger.step("CHECKOUT", "SUCCESS")
                else:
                    self._fatal("ORDER_ID_EXTRACTION_FAILED")
            except Exception:
                self._fatal("ORDER_ID_EXTRACTION_FAILED")

        # ------------------------------------------------------------------
    # MAIN ENTRY
    # ------------------------------------------------------------------
    def _check_driver_health(self):
        """Check if driver is still responsive"""
        try:
            if not self.driver:
                return False
            # Try to get current URL as health check
            _ = self.driver.current_url
            return True
        except (WebDriverException, AttributeError, Exception):
            # Driver is None, closed, or invalid
            return False
    
    def run(self, otp_supplier=None):
        try:
            # Verify chromedriver exists before attempting to use it (skip check if using system PATH)
            if self.CHROMEDRIVER_PATH != "chromedriver" and not os.path.exists(self.CHROMEDRIVER_PATH):
                error_msg = f"ChromeDriver not found at: {self.CHROMEDRIVER_PATH}\nPlease ensure chromedriver is available in PATH or in the same directory as main.py"
                self.logger.error(error_msg)
                raise FileNotFoundError(error_msg)
            
            try:
                self.driver = webdriver.Chrome(service=self.service, options=self.options)
                # Set timeouts optimized for VPS stability
                # Reduced timeouts to fail faster and prevent resource exhaustion
                self.driver.set_page_load_timeout(60)  # Reduced from 120s for faster failure
                self.driver.set_script_timeout(30)  # Reduced from 120s for faster failure
                # Set implicit wait (reduced for faster failure detection)
                self.driver.implicitly_wait(3)  # Reduced from 5s
            except WebDriverException as e:
                self.logger.error(f"Failed to initialize ChromeDriver: {e}")
                self._fatal("DRIVER_INIT_FAILED")
            
            # hide webdriver flag
            try:
                self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => false});")
            except Exception:
                pass
            
            # Health check after initialization
            if not self._check_driver_health():
                self.logger.error("Driver health check failed after initialization")
                self._fatal("DRIVER_UNRESPONSIVE")

            # -------------------------
            # MAIN EXECUTION PIPELINE
            # -------------------------

            # 1) Login
            self.step_login(otp_supplier)
            if self.fatal_error:
                return self.fatal_code or "LOGIN_FAILED"

            # 2) Add Address
            self.step_add_address()
            if self.fatal_error:
                return self.fatal_code or "ADDRESS_FAILED"
            time.sleep(1.2)

            # 3) Clear cart
            self.step_clear_cart()
            if self.fatal_error:
                return self.fatal_code or "CLEAR_CART_FAILED"
            time.sleep(1.2)

            # 4) Add products
            self.step_add_all_products()
            if self.fatal_error:
                return self.fatal_code or "ADD_PRODUCTS_FAILED"

            # 5) Apply cart deal (Deal Booster) - ALWAYS try to apply deals
            time.sleep(4)
            self.step_apply_cart_deals(self.deal_keyword)  # Works with or without keyword
            if self.fatal_error:
                return self.fatal_code or "DEAL_APPLY_FAILED"
            time.sleep(1.5)

            # 6) Apply coupon (MANUAL or AUTO APPLY)
            if self.coupon not in ("", None, "None"):
                time.sleep(2)
                self.step_apply_coupon(use_coupon=True)
                if self.fatal_error:
                    return self.fatal_code or "COUPON_FAILED"
                time.sleep(2)

            # 7) Checkout
            self.step_checkout()
            if self.fatal_error:
                return self.fatal_code or "CHECKOUT_FAILED"

            # normal completion returns order_id
            return self.order_id

        except FatalBotError as fe:
            # Already handled in _fatal; return short code to caller
            code = str(fe)
            self.logger.error(f"FatalBotError caught: {code}")
            return code

        except WebDriverException as wde:
            # Handle WebDriver crashes gracefully
            self.logger.error(f"WebDriverException: {wde}")
            if not self._check_driver_health():
                self.logger.error("Driver is unresponsive, marking as crash")
                self._fatal("DRIVER_CRASH")
            else:
                self._fatal("WEBDRIVER_ERROR")

        except Exception as e:
            # ANY unexpected error → stop immediately with _fatal
            self.logger.error(f"Unexpected error occurred: {e}")
            import traceback
            self.logger.error(f"Traceback:\n{traceback.format_exc()}")
            self._fatal("UNEXPECTED_ERROR")

        finally:
            # Aggressive cleanup for Linux VPS stability
            try:
                if self.driver:
                    # Check driver health before quitting
                    try:
                        if self._check_driver_health():
                            # Try graceful quit first
                            try:
                                self.driver.quit()
                            except Exception:
                                # If quit fails, force kill
                                try:
                                    if hasattr(self.driver, 'service') and self.driver.service:
                                        self.driver.service.process.kill()
                                except Exception:
                                    pass
                        else:
                            # Force kill if unresponsive
                            try:
                                if hasattr(self.driver, 'service') and self.driver.service:
                                    self.driver.service.process.kill()
                            except Exception:
                                pass
                    except Exception:
                        # If driver is already closed/invalid, just clear reference
                        pass
                    finally:
                        # Always clear reference after quit attempt
                        self.driver = None
                        
                    # Additional cleanup for Linux VPS - kill orphan processes
                    if platform.system() == "Linux":
                        try:
                            import subprocess
                            # Kill any remaining Chrome processes for this session
                            subprocess.run(
                                ["pkill", "-9", "-f", f"chromedriver.*{self.session_id}"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                timeout=2
                            )
                        except Exception:
                            pass
            except Exception:
                pass

# ------------------------------------------------------------------------------
# Stand-alone test
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("[TOP] Script started")
    from imap import otp
    print("[TOP] Imported otp supplier")

    PHONE = "flipkart342@husan.shop"
    ADDRESS = {
        "name": "Dinesh Singh", "phone": "9303530524", "pincode": "580020",
        "address_line1": "Near Railway Station, Main Road", "address_line2": "Ward No 12"
    }
    PRODUCTS = {
        
        "https://www.flipkart.com/fortune-chakki-fresh-atta/p/itmf8zjux3v4utqz?pid=FLRF8ZJU5KHYVCDC&lid=LSTFLRF8ZJU5KHYVCDC99ZMRY&hl_lid=&marketplace=GROCERY&pageUID=1766489331414": 1
    }
    keyword = "MTR"

    print("[TOP] Creating sniper instance...")
    sniper = FlipkartSniper(
        phone_number=PHONE,
        address_data=ADDRESS,
        products_dict=PRODUCTS,
        max_price=1200,
        coupon="FKGPMzUYMHEDBJJYPXEB"
        
    )
    print("[TOP] Calling run()...")
    result = sniper.run(otp_supplier=otp)
    print("[TOP] run() returned ->", result)
    print("[TOP] script finished")