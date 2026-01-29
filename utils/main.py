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
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level}] {message}"
        
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
                 coupon="None", deal_keyword="", session_id=None, headless=None, allow_less_qty=True):
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
        os.makedirs("screenshots", exist_ok=True)
        self.options = webdriver.ChromeOptions()
        
        # Auto-enable headless on Windows for better performance (can be overridden)
        if headless is None:
            headless = platform.system() == "Windows"
        
        # Enable headless mode with optimizations
        if headless:
            self.options.add_argument("--headless=new")
            self.logger.info("Headless mode enabled")
        else:
            self.options.add_argument("--window-size=600,500")
        
        # Critical VPS/Linux flags
        self.options.add_argument("--no-sandbox")
        self.options.add_argument("--disable-dev-shm-usage")
        self.options.add_argument("--disable-gpu")
        self.options.add_argument("--disable-software-rasterizer")
        
        # Anti-detection & Performance
        self.options.add_argument("--disable-blink-features=AutomationControlled")
        self.options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.options.add_experimental_option("useAutomationExtension", False)
        
        # Resource optimization
        self.options.add_argument("--disable-extensions")
        self.options.add_argument("--disable-background-networking")
        self.options.add_argument("--disable-background-timer-throttling")
        self.options.add_argument("--disable-renderer-backgrounding")
        self.options.add_argument("--disable-features=TranslateUI,AudioServiceOutOfProcess,IsolateOrigins,site-per-process")
        self.options.add_argument("--disable-ipc-flooding-protection")
        self.options.add_argument("--disable-infobars")
        self.options.add_argument("--disable-notifications")
        self.options.add_argument("--disable-sync")
        self.options.add_argument("--metrics-recording-only")
        self.options.add_argument("--no-first-run")
        self.options.add_argument("--ignore-certificate-errors")
        
        # Memory optimization
        self.options.add_argument("--memory-pressure-off")
        self.options.add_argument("--js-flags=--max-old-space-size=512")
        
        if platform.system() == "Linux":
             # specific linux optimizations
            self.options.add_argument("--disable-setuid-sandbox")
            self.options.add_argument("--single-process") # Helps with stability in some VPS containers
            self.options.add_argument("--disable-zygot") # Can help if zygote process crashes

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
            "deviceMetrics": {"width": 600, "height": 500, "pixelRatio": 2.0},
            "userAgent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        }
        self.options.add_experimental_option("mobileEmulation", mobile_emulation)

    # -----------------------
    # Fatal handler helper
    # -----------------------

    IMGBB_API_KEY = "867820c7c2f074c1d1dc81daa8cf7daf"

    @staticmethod
    def upload_screenshot_to_imgbb(path, api_key):
        try:
            with open(path, "rb") as f:
                res = requests.post(
                    "https://api.imgbb.com/1/upload",
                    data={"key": api_key},
                    files={"image": f}
                )
            data = res.json()
            return data["data"]["url"]
        except Exception as e:
            print("[IMG_UPLOAD] Failed:", e)
            return None


    def _fatal(self, code):
        """Stop bot immediately on any error. This function MUST be called for all errors."""
        self.fatal_error = True
        self.fatal_code = code
        timestamp = int(time.time())
        screenshot_path = f"screenshots/{code}_{timestamp}.png"

        self.logger.fatal(f"{code} → STOPPING BOT IMMEDIATELY")
        self.logger.log(f"{'='*60}", "FATAL")

        # Capture screenshot
        try:
            if self.driver and self._check_driver_health():
                self.driver.save_screenshot(screenshot_path)
                self.logger.log(f"Screenshot saved: {screenshot_path}", "FATAL")
            else:
                self.logger.warning("Driver not available for screenshot capture")
        except Exception as e:
            self.logger.error(f"Could not capture screenshot: {e}")

        # Upload screenshot
        url = FlipkartSniper.upload_screenshot_to_imgbb(
            screenshot_path, FlipkartSniper.IMGBB_API_KEY
        )
        if url:
            self.logger.log(f"Screenshot URL: {url}", "FATAL")
        else:
            self.logger.error("Screenshot upload failed")

        # Quit browser safely
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None  # Clear reference to prevent double-quit
                self.logger.log("Browser closed", "FATAL")
        except Exception as e:
            self.logger.error(f"Error closing browser: {e}")
            # Even if quit fails, clear the reference to prevent further operations
            self.driver = None

        # Raise exception to stop execution immediately
        raise FatalBotError(f"{code} | {url or 'NO_SCREENSHOT'}")


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
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center', behavior:'smooth'});", element)
                time.sleep(0.3)
                
                # Try JavaScript click first (most reliable)
                self.driver.execute_script("arguments[0].click();", element)
                time.sleep(0.2)
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
        element.clear()
        element.send_keys(Keys.CONTROL + "a")
        element.send_keys(Keys.DELETE)
        element.send_keys(text)

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

    # ------------------------------------------------------------------
    # Clear cart
    # ------------------------------------------------------------------
    def step_clear_cart(self):
        self.logger.step("CLEAR_CART", "STARTED")
        self.logger.info("Navigating to cart page...")
        self.driver.get("https://www.flipkart.com/viewcart?marketplace=GROCERY")
        time.sleep(0.5)
        removed_count = 0
        while True:
            removed = False
            for xpath in [
                "//img[contains(@src,'d60e8bff')]/parent::div",
                "//div[text()='Remove ' and contains(@class,'r-op4f77')]"
            ]:
                try:
                    el = self.q(1).until(EC.element_to_be_clickable((By.XPATH, xpath)))
                    self.safe_click(el)
                    time.sleep(0.5)
                    try:
                        self.safe_click(self.driver.find_element(By.XPATH, "//button[text()='Remove' or text()='REMOVE']"))
                        time.sleep(0.5)
                    except Exception:
                        pass
                    removed = True
                    removed_count += 1
                    self.logger.info(f"Removed item #{removed_count} from cart")
                    time.sleep(0.7)
                except Exception:
                    pass
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
        self.driver.get(product_url)
        time.sleep(1.5)

        # Get product name first
        # Get product name with robust fallbacks
        try:
            # Try 1: Known robust classes
            try:
                product_name_element = self.driver.find_element(By.CSS_SELECTOR, "span.B_NuCI, h1.yhB1nd, h1")
                product_name = product_name_element.text.strip()
            except:
                 # Try 2: The complex React class (original one) as a fallback
                product_name_element = self.q(2).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.css-1rynq56.r-8akbws.r-krxsd3.r-dnmrzs.r-1udh08x.r-1udbk01"))
                )
                product_name = product_name_element.text.strip()
            
            self.logger.info(f"Product Name: {product_name}")
        except Exception as e:
            # Try 3: Last resort - generic non-empty h1
            try:
                 h1s = self.driver.find_elements(By.TAG_NAME, "h1")
                 for h in h1s:
                     if h.is_displayed() and len(h.text.strip()) > 5:
                         product_name = h.text.strip()
                         self.logger.info(f"Product Name (fallback): {product_name}")
                         break
                 else:
                     raise Exception("No suitable h1 found")
            except:
                self.logger.warning(f"Could not extract product name: {e}")
                product_name = "Unknown Product"

        # Click Add
        try:
            self.logger.info("Clicking Add button...")
            self.safe_click(self.q(5).until(
                EC.element_to_be_clickable((By.XPATH, "//div[text()='Add']"))
            ))
            time.sleep(1)
            self.logger.info("Add button clicked successfully")
        except Exception:
            # Product "Add" button not present → treat as OOS, but capture better context first
            self.logger.error("Add button not found - scrolling and preventing OOS misfire")
            
            # Scroll down to capture more context in screenshot
            try:
                self.logger.info("Attempting scroll via PAGE_DOWN and JS...")
                try:
                    self.driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.PAGE_DOWN)
                except:
                    pass
                self.driver.execute_script("window.scrollBy(0, 600);")
                time.sleep(2)
            except Exception as e:
                self.logger.warning(f"Scroll failed: {e}")
                
            # Capture debug screenshot before erroring
            try:
                ts = int(time.time())
                path = f"screenshots/PRODUCT_OOS_SCROLL_{ts}.png"
                self.driver.save_screenshot(path)
                url = FlipkartSniper.upload_screenshot_to_imgbb(path, FlipkartSniper.IMGBB_API_KEY)
                self.logger.info(f"OOS Context Screenshot: {url}")
            except:
                pass

            self._fatal("PRODUCT_OUT_OF_STOCK")

        qty_xpath = "//div[contains(@class,'r-1cenzwm') and contains(@class,'r-1b43r93')]"
        increase_btn_xpath = "(//div[contains(@style,'rgb(133, 60, 14)')])[last()]"

        # Two attempts to update quantity and find maximum available
        max_available_qty = 0
        for attempt in range(1, 3):
            try:
                qty_el = self.q(4).until(EC.presence_of_element_located((By.XPATH, qty_xpath)))
                qty_text = qty_el.text.strip()
                current_qty = int("".join(filter(str.isdigit, qty_text))) if qty_text else 0
                max_available_qty = current_qty  # Track the max we've seen

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
                    qty_text = qty_el.text.strip()
                    final_qty = int("".join(filter(str.isdigit, qty_text))) if qty_text else 0
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
            final_text = qty_el.text.strip()
            final_qty = int("".join(filter(str.isdigit, final_text))) if final_text else 0
            max_available_qty = max(max_available_qty, final_qty)
            if final_qty >= desired_qty:
                self.logger.success(f"FINAL QUANTITY: {final_qty}/{desired_qty} - SUCCESS")
            else:
                self.logger.warning(f"FINAL QUANTITY: {final_qty}/{desired_qty} - LESS THAN DESIRED")
            
            # Only record warnings if there's an actual quantity issue
            if max_available_qty < desired_qty:
                if not self.allow_less_qty:
                    # If allow_less_qty is disabled, this is a fatal error
                    self.logger.error(f"[STOCK] Maximum available quantity {max_available_qty} < desired {desired_qty} and allow_less_qty is disabled - stopping all workers")
                    self._record_stock_warning(product_name, product_url, desired_qty, max_available_qty)
                    self._fatal("QTY_TOO_LOW")  # This will raise FatalBotError
                else:
                    # If allow_less_qty is enabled, just record a warning (not fatal)
                    self._record_stock_warning(product_name, product_url, desired_qty, max_available_qty)
                    self.logger.warning(f"[STOCK] Available quantity {max_available_qty} < desired {desired_qty} but allow_less_qty is enabled - continuing")
            # If final_qty >= desired_qty, no warning needed - quantity is sufficient
        except FatalBotError:
            raise  # Re-raise fatal errors immediately
        except Exception as e:
            # If verification fails, fatal because quantity is important
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
    def step_apply_cart_deals(self, target_first_word):
        target_first_word = (target_first_word or "").upper().strip()
        
        self.logger.step("APPLY_DEALS", "STARTED")
        deal_buttons = self.driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'css-1rynq56') and (normalize-space(text())='Add' or normalize-space(text())='Apply deal' or normalize-space(text())='Apply Deal')]"
        )
        self.logger.info(f"Found {len(deal_buttons)} deal button(s)")
        
        if not deal_buttons:
            self.logger.info("No deal buttons found, skipping deal application")
            self.logger.step("APPLY_DEALS", "SKIPPED")
            return
        
        # Collect all products with their buttons
        products_with_buttons = []
        for idx, btn in enumerate(deal_buttons, start=1):
            try:
                parent = btn
                product_name = None
                for _ in range(10):
                    parent = parent.find_element(By.XPATH, "./parent::*")
                    try:
                        name_el = parent.find_element(
                            By.XPATH,
                            ".//div[contains(@class,'css-1rynq56') and contains(@style,'font-size: 12px')]"
                        )
                        product_name = name_el.text.strip()
                        break
                    except Exception:
                        continue
                if product_name:
                    first_word = product_name.split()[0].upper()
                    products_with_buttons.append({
                        "index": idx - 1,  # 0-based index
                        "name": product_name,
                        "first_word": first_word,
                        "button": btn
                    })
                    self.logger.info(f"Product #{idx}: '{product_name}' → First word: {first_word}")
            except Exception as e:
                self.logger.warning(f"Error extracting product name for button #{idx}: {e}")
                continue
        
        if not products_with_buttons:
            self.logger.warning("Could not extract any product names, skipping deal application")
            self.logger.step("APPLY_DEALS", "SKIPPED")
            return
        
        # Case 1: If deal_keyword is NOT provided, automatically click first deal
        if not target_first_word:
            self.logger.info("No deal keyword provided → automatically clicking first deal")
            try:
                first_product = products_with_buttons[0]
                self.logger.info(f"Auto-selecting: '{first_product['name']}'")
                self.safe_click(first_product["button"])
                time.sleep(1.2)
                self.logger.success(f"Deal applied: '{first_product['name']}'")
                self.logger.step("APPLY_DEALS", "SUCCESS")
                return
            except Exception as e:
                self.logger.error(f"Error clicking first deal: {e}")
                self.logger.step("APPLY_DEALS", "FAILED")
                return
        
        # Case 2: If deal_keyword IS provided, try to find match
        self.logger.info(f"Searching for deal matching keyword: '{target_first_word}'")
        matched_index = None
        for idx, product in enumerate(products_with_buttons):
            if product["first_word"] == target_first_word:
                matched_index = idx
                self.logger.success(f"MATCH! Found '{product['name']}' → Clicking")
                self.safe_click(product["button"])
                time.sleep(1.2)
                self.logger.success(f"Deal applied: '{product['name']}'")
                self.logger.step("APPLY_DEALS", "SUCCESS")
                return
        
        # Case 3: deal_keyword provided but NOT found → show selection modal
        self.logger.warning(f"No match found for '{target_first_word}' → showing selection modal")
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            files_dir = os.path.join(base_dir, "..", "files")
            os.makedirs(files_dir, exist_ok=True)
            deal_selection_file = os.path.join(files_dir, "deal_selection.json")
            deal_response_file = os.path.join(files_dir, "deal_response.json")
            
            # Write deal selection request
            selection_data = {
                "status": "pending",
                "session_id": self.session_id or f"session_{int(time.time())}",
                "products": [{"index": p["index"], "name": p["name"]} for p in products_with_buttons],
                "matched_index": None,  # No match found
                "timestamp": time.time()
            }
            with open(deal_selection_file, "w", encoding="utf-8") as f:
                json.dump(selection_data, f, indent=2)
            
            self.logger.info(f"Waiting for user selection (session: {selection_data['session_id']})...")
            self.logger.info("Available products:")
            for p in products_with_buttons:
                self.logger.info(f"  {p['index'] + 1}) {p['name']}")
            
            # Poll for user selection (wait up to 5 minutes)
            max_wait_time = 300  # 5 minutes
            poll_interval = 2  # Check every 2 seconds
            start_time = time.time()
            
            while (time.time() - start_time) < max_wait_time:
                if os.path.exists(deal_response_file):
                    try:
                        with open(deal_response_file, "r", encoding="utf-8") as f:
                            response_data = json.load(f)
                        
                        # Check if response is for this session
                        if response_data.get("session_id") == selection_data["session_id"]:
                            selected_index = response_data.get("selected_index")
                            
                            # Clean up response file
                            try:
                                os.remove(deal_response_file)
                            except:
                                pass
                            
                            # Clean up selection file
                            try:
                                os.remove(deal_selection_file)
                            except:
                                pass
                            
                            if selected_index is None:
                                self.logger.warning("User cancelled deal selection")
                                self.logger.step("APPLY_DEALS", "CANCELLED")
                                return
                            
                            if 0 <= selected_index < len(products_with_buttons):
                                selected_product = products_with_buttons[selected_index]
                                self.logger.info(f"User selected: '{selected_product['name']}' → Clicking")
                                self.safe_click(selected_product["button"])
                                time.sleep(1.2)
                                self.logger.success(f"Deal applied: '{selected_product['name']}'")
                                self.logger.step("APPLY_DEALS", "SUCCESS")
                                return
                            else:
                                self.logger.error(f"Invalid selection index: {selected_index}")
                                self.logger.step("APPLY_DEALS", "FAILED")
                                return
                    except Exception as e:
                        self.logger.error(f"Error reading response: {e}")
                
                time.sleep(poll_interval)
            
            # Timeout - clean up and continue
            self.logger.warning("Selection timeout - no deal will be applied")
            try:
                if os.path.exists(deal_selection_file):
                    os.remove(deal_selection_file)
                if os.path.exists(deal_response_file):
                    os.remove(deal_response_file)
            except:
                pass
            self.logger.step("APPLY_DEALS", "TIMEOUT")
            
        except Exception as e:
            self.logger.error(f"Error in deal selection modal: {e}")
            import traceback
            traceback.print_exc()
            self.logger.step("APPLY_DEALS", "FAILED")

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
        # (Note: Even if Apply button is found, we'll still enter coupon first)
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
                                self.logger.info("Found Apply button after opening section → will enter coupon first, then click it")
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
        # ENTER COUPON MANUALLY (always enter coupon if section is open)
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

                # If we found an Apply button earlier, use that one; otherwise find a new one
                if apply_button_found_after_open and apply_button_element:
                    self.logger.info("Clicking the Apply button found earlier (after entering coupon)")
                    self.safe_click(apply_button_element)
                    self.apply_button_used = True
                else:
                    # Find Apply button normally
                    self.logger.info("Finding and clicking Apply button...")
                    apply_btn = self.q(5).until(EC.any_of(
                        EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'css-1rynq56') and normalize-space(text())='Add Coupon']")),
                        EC.element_to_be_clickable((By.XPATH, "//div[text()='Apply']")),
                    ))
                    self.safe_click(apply_btn)
                
                self.logger.success("APPLY BUTTON CLICKED — COUPON APPLIED!")
                time.sleep(2)

                # Detect ANY coupon error
                try:
                    coupon_error = self.driver.find_element(
                        By.XPATH,
                        "//div[contains(@class,'css-1rynq56') and (contains(text(),'Invalid coupon') or contains(text(),'max usage'))]"
                    )
                    if coupon_error.is_displayed():
                        msg = coupon_error.text.strip()
                        self.logger.error(f"COUPON ERROR DETECTED → {msg}")
                        if "max usage" in msg.lower():
                            self._fatal("COUPON_MAX_USAGE_LIMIT")
                        else:
                            self._fatal("INVALID_COUPON")
                except NoSuchElementException:
                    pass
                
                self.logger.step("APPLY_COUPON", "SUCCESS")

            except FatalBotError:
                # re-raise fatal so outer run() can catch and return code
                raise
            except Exception as e:
                self.logger.error(f"Coupon apply failed: {e}")
                self._fatal("COUPON_APPLY_ERROR")
            try:
                btn = self.driver.find_element(By.XPATH, "//a[contains(@class,'jlLn4z')]")
                self.driver.execute_script("arguments[0].click();", btn)   
            except Exception as e:
                self._fatal("BACK_ICON_NOT_FOUND")
                                            

    # ------------------------------------------------------------------
    # Checkout & order
    # ------------------------------------------------------------------
    def step_checkout(self):
        self.logger.step("CHECKOUT", "STARTED")
        
        # Check driver health before critical checkout operations
        if not self._check_driver_health():
            self._fatal("DRIVER_UNRESPONSIVE")

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

        # SECOND CONTINUE
        try:
            second_continue = self.q(5).until(EC.presence_of_element_located((
                By.XPATH, "//div[contains(@style,'rgb(255, 194, 0)') and .//div[normalize-space(.)='Continue']]"
            )))
            self.safe_click(second_continue)
            self.logger.info("Second Continue clicked")
        except FatalBotError:
            raise  # Re-raise fatal errors immediately
        except Exception:
            self.logger.info("No second continue (might not be needed)")

        # PRICE VALIDATION
        try:
            price_xpath = "//span[@data-testid='price' and contains(@class,'font-l-semibold')]"
            self.q(10).until(EC.presence_of_element_located((By.XPATH, price_xpath)))
            price_text = self.driver.find_element(By.XPATH, price_xpath).text.strip()

            digits = "".join(filter(str.isdigit, price_text))
            if digits:
                numeric_price = int(digits)
                self.logger.info(f"Price validation: {numeric_price} (max: {self.max_price})")
                if numeric_price > self.max_price:
                    self._fatal("PRICE_TOO_HIGH")
        except FatalBotError:
            raise  # Re-raise fatal errors immediately
        except Exception as e:
            self.logger.error(f"Price validation error: {e}")
            self._fatal("PRICE_VALIDATION_ERROR")

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
            
            # Click delivery date using class selector
            try:
                delivery = self.driver.find_elements(By.CSS_SELECTOR, "span.yxF9fy")
                if delivery:
                    self.safe_click(delivery[0])
                    time.sleep(2)
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
                    screenshot_path = f"screenshots/order_{self.order_id}_{timestamp}.png"
                    self.driver.save_screenshot(screenshot_path)
                    self.logger.log(f"Screenshot saved: {screenshot_path}", "SUCCESS")
                    
                    # Upload screenshot and get URL
                    screenshot_url = FlipkartSniper.upload_screenshot_to_imgbb(
                        screenshot_path, FlipkartSniper.IMGBB_API_KEY
                    )
                    if screenshot_url:
                        self.screenshot_url = screenshot_url
                        self.logger.log(f"Screenshot URL: {screenshot_url}", "SUCCESS")
                    else:
                        self.screenshot_url = "NONE"
                        self.logger.warning("Screenshot upload failed, using NONE")
                except Exception as e:
                    self.logger.error(f"Could not capture/upload screenshot: {e}")
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
                        screenshot_path = f"screenshots/order_{self.order_id}_{timestamp}.png"
                        self.driver.save_screenshot(screenshot_path)
                        self.logger.log(f"Screenshot saved: {screenshot_path}", "SUCCESS")
                        
                        # Upload screenshot and get URL
                        screenshot_url = FlipkartSniper.upload_screenshot_to_imgbb(
                            screenshot_path, FlipkartSniper.IMGBB_API_KEY
                        )
                        if screenshot_url:
                            self.screenshot_url = screenshot_url
                            self.logger.log(f"Screenshot URL: {screenshot_url}", "SUCCESS")
                        else:
                            self.screenshot_url = "NONE"
                            self.logger.warning("Screenshot upload failed, using NONE")
                    except Exception as screenshot_error:
                        self.logger.error(f"Could not capture/upload screenshot: {screenshot_error}")
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
                # Set page load timeout to prevent hanging
                self.driver.set_page_load_timeout(30)
                # Set implicit wait
                self.driver.implicitly_wait(5)
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

            # 5) Apply cart deal (Deal Booster)
            if self.deal_keyword not in ("", None):
                time.sleep(2)
                self.step_apply_cart_deals(self.deal_keyword)
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
            # ensure driver is quit (silent)
            try:
                if self.driver:
                    # Check driver health before quitting
                    try:
                        if self._check_driver_health():
                            self.driver.quit()
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
            except Exception:
                pass

# ------------------------------------------------------------------------------
# Stand-alone test
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("[TOP] Script started")
    from imap import otp
    print("[TOP] Imported otp supplier")

    PHONE = "nigga@heyalex.store"
    ADDRESS = {
        "name": "Dinesh Singh", "phone": "9303530534", "pincode": "580020",
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