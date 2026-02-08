#!/usr/bin/env python3

import os
import time
import csv
from multiprocessing import Process, Queue, Lock
from pathlib import Path
import sys
import subprocess
import platform

# ==========================================================
# GLOBAL CONFIG
# ==========================================================
MAX_PARALLEL = 1  # Reduced to 1 for VPS stability

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FILES_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "files"))
DOWNLOAD_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "download"))

os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAIL_FILE = os.path.join(FILES_DIR, "mail.txt")
USED_MAIL_FILE = os.path.join(FILES_DIR, "used_mail.txt")

COUPON_FILE = os.path.join(FILES_DIR, "coupon.txt")
USED_COUPON_FILE = os.path.join(FILES_DIR, "used_coupon.csv")

SUCCESS_COUPON = os.path.join(DOWNLOAD_DIR, "success_coupon.csv")
FAILED_COUPON = os.path.join(DOWNLOAD_DIR, "failed_coupon.csv")
SUCCESS_COUPON_TXT = os.path.join(FILES_DIR, "success_coupon.txt")
FAILED_COUPON_TXT = os.path.join(FILES_DIR, "failed_coupon.txt")

SUCCESS_CSV = os.path.join(DOWNLOAD_DIR, "success.csv")
FAILURE_CSV = os.path.join(DOWNLOAD_DIR, "failure.csv")
CANCELLED_LOG = os.path.join(DOWNLOAD_DIR, "cancelled.txt")
REMOVED_MAIL_FILE = os.path.join(DOWNLOAD_DIR, "removed_mails.txt")

DEFAULT_NAME = "Rahul Kumar"
DEFAULT_PHONE = "9303530519"
DEFAULT_PINCODE = "842001"
DEFAULT_ADDR1 = "Near Durga Mandir"
DEFAULT_ADDR2 = "Ward 12"

imap_lock = Lock()
resource_lock = Lock()

# Crash-type errors → Do NOT consume coupon permanently
CRASH_TYPES = ["CRASH", "OTP_NOT_RECEIVED", "PRODUCT_OUT_OF_STOCK", "CLICK_FAILED"]


# ==========================================================
# HELPERS
# ==========================================================
def pop_coupon():
    """
    Safely pop the first coupon from coupon.txt with locking.
    Returns the coupon string or None if empty.
    Optimized to avoid loading entire file for large coupon lists.
    """
    # #region agent log
    import json; log_file = r"c:\Users\zgarm\OneDrive\Desktop\flipkart automation\.cursor\debug.log"; open(log_file, "a", encoding="utf-8").write(json.dumps({"location":"connect.py:63","message":"pop_coupon entry","data":{"hypothesisId":"A"},"timestamp":int(__import__("time").time()*1000)})+"\n")
    # #endregion
    with resource_lock:
        if not os.path.exists(COUPON_FILE):
            # #region agent log
            open(log_file, "a", encoding="utf-8").write(json.dumps({"location":"connect.py:65","message":"COUPON_FILE not exists","data":{"hypothesisId":"A"},"timestamp":int(__import__("time").time()*1000)})+"\n")
            # #endregion
            return None
        
        temp_file = COUPON_FILE + ".tmp"
        coupon = None
        first_line = True
        
        try:
            with open(COUPON_FILE, "r", encoding="utf-8") as infile, open(temp_file, "w", encoding="utf-8") as outfile:
                for line in infile:
                    # #region agent log
                    open(log_file, "a", encoding="utf-8").write(json.dumps({"location":"connect.py:73","message":"Raw line from file","data":{"raw_line":repr(line),"has_backslash_n":"\\n" in line,"hypothesisId":"A"},"timestamp":int(__import__("time").time()*1000)})+"\n")
                    # #endregion
                    stripped = line.strip().replace("\\n", "")
                    # #region agent log
                    open(log_file, "a", encoding="utf-8").write(json.dumps({"location":"connect.py:74","message":"After strip and replace","data":{"stripped":repr(stripped),"has_backslash_n":"\\n" in stripped,"hypothesisId":"A"},"timestamp":int(__import__("time").time()*1000)})+"\n")
                    # #endregion
                    if not stripped:
                        continue
                    if first_line:
                        coupon = stripped  # First non-empty line is the coupon to pop
                        # #region agent log
                        open(log_file, "a", encoding="utf-8").write(json.dumps({"location":"connect.py:78","message":"Coupon extracted","data":{"coupon":repr(coupon),"has_backslash_n":"\\n" in coupon,"hypothesisId":"A"},"timestamp":int(__import__("time").time()*1000)})+"\n")
                        # #endregion
                        first_line = False
                    else:
                        outfile.write(stripped + "\n")  # Write remaining lines
            
            if coupon:
                # Atomic replace only if we found a coupon
                os.replace(temp_file, COUPON_FILE)
                # #region agent log
                open(log_file, "a", encoding="utf-8").write(json.dumps({"location":"connect.py:85","message":"Coupon returned","data":{"coupon":repr(coupon),"has_backslash_n":"\\n" in coupon,"hypothesisId":"A"},"timestamp":int(__import__("time").time()*1000)})+"\n")
                # #endregion
            else:
                # No coupon found, remove temp file
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                return None
            
            return coupon
        except Exception as e:
            # Cleanup temp file on error
            if os.path.exists(temp_file):
                os.remove(temp_file)
            # #region agent log
            open(log_file, "a", encoding="utf-8").write(json.dumps({"location":"connect.py:97","message":"pop_coupon exception","data":{"error":str(e),"hypothesisId":"A"},"timestamp":int(__import__("time").time()*1000)})+"\n")
            # #endregion
            return None

def ensure_dirs():
    Path(FILES_DIR).mkdir(exist_ok=True)
    Path(DOWNLOAD_DIR).mkdir(exist_ok=True)


def load_lines_unique(path):
    """
    Load unique lines from file efficiently.
    Uses generator to avoid loading entire file into memory at once.
    """
    if not os.path.exists(path):
        return []
    seen = set()
    result = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                result.append(stripped)
    return result


def csv_write(path, header, row):
    """
    Safe CSV append with locking to avoid corruption when multiple processes
    write at the same time.
    """
    with resource_lock:
        new = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(header)
            w.writerow(row)


def kill_orphan_chrome():
    """
    Best-effort kill of stray chromedriver and Chrome processes.
    More aggressive cleanup for Linux VPS with limited resources.
    """
    try:
        if platform.system().lower().startswith("win"):
            # Kill chromedriver.exe processes
            subprocess.run(
                ["taskkill", "/F", "/T", "/IM", "chromedriver.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            # DO NOT kill chrome.exe on Windows - it kills user's main browser!
            # subprocess.run(
            #     ["taskkill", "/F", "/T", "/IM", "chrome.exe"],
            #     stdout=subprocess.DEVNULL,
            #     stderr=subprocess.DEVNULL,
            #     timeout=5
            # )
        else:
            # Unix-like: More aggressive cleanup for Linux VPS
            # Kill chromedriver processes
            subprocess.run(
                ["pkill", "-9", "-f", "chromedriver"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            # Kill all Chrome processes (headless and regular)
            subprocess.run(
                ["pkill", "-9", "-f", "chrome"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            # Also try killing by process name directly
            subprocess.run(
                ["killall", "-9", "chrome", "chromedriver"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            # Clean up /tmp/chrome* files that might cause issues
            try:
                import glob
                for tmp_file in glob.glob("/tmp/.com.google.Chrome*"):
                    try:
                        os.remove(tmp_file)
                    except:
                        pass
            except:
                pass
    except subprocess.TimeoutExpired:
        # Process kill timed out, continue
        pass
    except Exception:
        # Ignore failures; this is best-effort cleanup
        pass


def restore_pending_coupons_on_stop():
    """
    If workers are cancelled, put any PENDING coupons back to coupon.txt
    and remove those pending rows from used_coupon.csv. Log the action.
    """
    with resource_lock:
        pending = []
        header = None
        rows = []
        if os.path.exists(USED_COUPON_FILE):
            with open(USED_COUPON_FILE, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if i == 0:
                        header = row
                        continue
                    if len(row) >= 2 and row[1].upper() == "PENDING":
                        pending.append(row[0])
                    else:
                        rows.append(row)

        if pending:
            # Restore coupons to coupon.txt (append)
            # Clean coupons before restoring to remove any \n characters
            import re
            with open(COUPON_FILE, "a", encoding="utf-8") as f:
                for c in pending:
                    # Clean the coupon: remove literal \n sequences and actual newlines
                    cleaned = c.strip()
                    cleaned = re.sub(r'\\+n', '', cleaned)
                    cleaned = cleaned.replace('\n', '').replace('\r', '').strip()
                    if cleaned:  # Only write non-empty cleaned coupons
                        f.write(cleaned + "\n")

            # Rewrite used_coupon.csv without pending rows
            with open(USED_COUPON_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if header:
                    writer.writerow(header)
                for r in rows:
                    writer.writerow(r)

            # Log cancellations
            with open(CANCELLED_LOG, "a", encoding="utf-8") as f:
                for c in pending:
                    f.write(f"CANCELLED_COUPON,{c},{int(time.time())}\n")


def write_success(email, pin, coupon, oid, screenshot_url="NONE"):
    csv_write(
        SUCCESS_CSV,
        ["email", "postal_code", "order_id", "invoice_image_url"],
        [email, pin, oid, screenshot_url],
    )


def write_failure(email, pin, coupon, error, screenshot_url="NONE"):
    csv_write(
        FAILURE_CSV,
        ["email", "postal_code", "coupon", "error", "invoice_image_url"],
        [email, pin, coupon, error, screenshot_url],
    )


def log_success_coupon(coupon, email, order_id, screenshot_url="NONE"):
    csv_write(
        SUCCESS_COUPON,
        ["coupon", "email", "order_id", "screenshot_url"],
        [coupon, email, order_id, screenshot_url],
    )
    with resource_lock:
        with open(SUCCESS_COUPON_TXT, "a", encoding="utf-8") as f:
            f.write(f"{coupon},{email},{order_id},{screenshot_url}\n")


def log_failed_coupon(coupon, email, error, screenshot_url="NONE"):
    """
    Log failed coupon to failed_coupon.csv with only coupon and screenshot_url.
    Note: This should be called along with write_failure() for coupon errors.
    """
    csv_write(
        FAILED_COUPON,
        ["coupon", "screenshot_url"],  # Changed: only coupon and screenshot_url
        [coupon, screenshot_url],  # Changed: only coupon and screenshot_url
    )
    with resource_lock:
        with open(FAILED_COUPON_TXT, "a", encoding="utf-8") as f:
            f.write(f"{coupon},{screenshot_url}\n")  # Changed: only coupon and screenshot_url


def push_mail_to_bottom(email):
    """
    Move the given mail line (by base email) to bottom of mail.txt
    so failures get retried later.
    Optimized to avoid loading entire file into memory.
    """
    with resource_lock:
        if not os.path.exists(MAIL_FILE):
            return
        
        base = email.split(",")[0]
        temp_file = MAIL_FILE + ".tmp"
        
        try:
            with open(MAIL_FILE, "r", encoding="utf-8") as infile, open(temp_file, "w", encoding="utf-8") as outfile:
                for line in infile:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    # Keep line if it's not the email we're moving
                    if stripped.split(",")[0] != base:
                        outfile.write(stripped + "\n")
                # Append the email to bottom
                outfile.write(email + "\n")
            
            # Atomic replace
            os.replace(temp_file, MAIL_FILE)
        except Exception as e:
            # Cleanup temp file on error
            if os.path.exists(temp_file):
                os.remove(temp_file)
            raise


def log_used_mail(email):
    """Append successfully used mail to used_mail.txt and removed_mails.txt (thread-safe)."""
    with resource_lock:
        # Write to used_mail.txt (in files folder)
        with open(USED_MAIL_FILE, "a", encoding="utf-8") as f:
            f.write(email.strip() + "\n")
        # Also write to removed_mails.txt (in downloads folder)
        with open(REMOVED_MAIL_FILE, "a", encoding="utf-8") as f:
            f.write(email.strip() + "\n")


def save_used_lines(used_list, src, dest):
    """
    Move successfully used mails from MAIL_FILE → USED_MAIL_FILE
    Optimized to avoid reading entire file into memory for large files.
    """
    if not used_list:
        return

    # #region agent log
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cursor")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "debug.log")
    try:
        import json
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"E","location":"connect.py:231","message":"save_used_lines called","data":{"used_list":used_list,"src":src,"dest":dest},"timestamp":int(time.time()*1000)}) + "\n")
    except: pass
    # #endregion

    used_set = set(used_list)

    with resource_lock:
        # Append to dest file (fast, no reading needed)
        with open(dest, "a", encoding="utf-8") as f:
            for it in used_list:
                f.write(it + "\n")
        # Also append to removed_mails.txt if moving from MAIL_FILE to USED_MAIL_FILE
        if src == MAIL_FILE and dest == USED_MAIL_FILE:
            with open(REMOVED_MAIL_FILE, "a", encoding="utf-8") as f:
                for it in used_list:
                    f.write(it + "\n")

        if not os.path.exists(src):
            # #region agent log
            try:
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"E","location":"connect.py:244","message":"save_used_lines: src file does not exist","data":{"src":src},"timestamp":int(time.time()*1000)}) + "\n")
            except: pass
            # #endregion
            return

        # Optimized: Write remaining lines directly without loading all into memory
        # Use temp file to avoid corruption on large files
        temp_file = src + ".tmp"
        lines_before = 0
        lines_after = 0
        
        try:
            with open(src, "r", encoding="utf-8") as infile, open(temp_file, "w", encoding="utf-8") as outfile:
                for line in infile:
                    lines_before += 1
                    stripped = line.strip()
                    if not stripped:
                        continue
                    # Check if this line should be kept (email not in used_set)
                    base = stripped.split(",")[0]
                    if base not in used_set:
                        outfile.write(stripped + "\n")
                        lines_after += 1
            
            # Atomic replace
            os.replace(temp_file, src)
        except Exception as e:
            # Cleanup temp file on error
            if os.path.exists(temp_file):
                os.remove(temp_file)
            raise

        # #region agent log
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"E","location":"connect.py:280","message":"save_used_lines: completed","data":{"lines_before":lines_before,"lines_after":lines_after,"removed_count":lines_before-lines_after},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion


# ==========================================================
# RESTORE COUPON (for non-coupon errors)
# ==========================================================
def restore_coupon(coupon):
    """
    Put coupon back into coupon.txt if it was temporarily removed.
    Returns True if coupon was restored, False otherwise.
    """
    if not coupon:
        print(f"[COUPON RESTORE] ⚠️ Cannot restore empty/None coupon")
        return False
    
    try:
        with resource_lock:
            # Clean the coupon: remove any literal \n sequences and actual newlines
            # This prevents restoring coupons with embedded newlines
            import re
            cleaned_coupon = coupon.strip()
            # Remove literal \n sequences (backslash followed by n)
            cleaned_coupon = re.sub(r'\\+n', '', cleaned_coupon)
            # Remove actual newline characters
            cleaned_coupon = cleaned_coupon.replace('\n', '').replace('\r', '')
            # Remove any remaining whitespace
            cleaned_coupon = cleaned_coupon.strip()
            
            if not cleaned_coupon:
                print(f"[COUPON RESTORE] ⚠️ Cannot restore coupon - cleaned coupon is empty")
                return False
            
            # Quick check if coupon exists (stop at first match for speed)
            coupon_exists = False
            if os.path.exists(COUPON_FILE):
                with open(COUPON_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        # Also clean the line for comparison
                        cleaned_line = line.strip()
                        cleaned_line = re.sub(r'\\+n', '', cleaned_line)
                        cleaned_line = cleaned_line.replace('\n', '').replace('\r', '').strip()
                        if cleaned_line == cleaned_coupon:
                            coupon_exists = True
                            print(f"[COUPON RESTORE] ℹ️ Coupon '{cleaned_coupon}' already exists in coupon.txt - skipping restore")
                            break
            
            # Only append if not exists (much faster than read-all, modify, write-all)
            if not coupon_exists:
                with open(COUPON_FILE, "a", encoding="utf-8") as f:
                    f.write(cleaned_coupon + "\n")
                print(f"[COUPON RESTORE] ✅ Successfully restored coupon '{cleaned_coupon}' to coupon.txt")
                return True
            return True  # Already exists, so technically "restored"
    except Exception as e:
        print(f"[COUPON RESTORE] ❌ ERROR: Failed to restore coupon '{coupon}': {e}")
        import traceback
        traceback.print_exc()
        return False


# ==========================================================
# ERROR PARSER
# ==========================================================
def split_error_and_url(val):
    """
    Parse "CODE | URL" into ("CODE", "URL").
    If no pipe found, returns (val, "NONE").
    """
    if not isinstance(val, str):
        return str(val), "NONE"
    if "|" not in val:
        return val.strip(), "NONE"
    left, right = val.split("|", 1)
    return left.strip(), right.strip() or "NONE"


# ==========================================================
# CONNECT RUNNER
# ==========================================================
class ConnectRunner:
    def __init__(
        self,
        products_dict,
        count_limit=None,
        max_price=9999,
        deal_keyword="",
        toggle_retry=False,
        allow_less_qty=True,
        remove_mail_on_success=True,
        max_parallel=MAX_PARALLEL,
        name=None,
        phone=None,
        pincode=None,
        address1=None,
        address2=None,
        use_coupon=True,
        auto_apply_deals=True,  # New parameter: auto-apply deals toggle
        headless=None,  # None = default (Headless on Linux, Configurable on Windows)
        screenshot_domain=None,  # New: Dynamic screenshot domain from UI
    ):
        self.max_parallel = max_parallel
        self.count_limit = count_limit
        self.max_price = max_price
        self.deal_keyword = deal_keyword
        self.toggle_retry = toggle_retry
        self.allow_less_qty = allow_less_qty
        self.remove_mail_on_success = remove_mail_on_success

        self.name = name
        self.phone = phone
        self.pincode = pincode
        self.address1 = address1
        self.address2 = address2

        # global toggle: whether to apply coupons in this batch
        self.use_coupon = True if str(use_coupon).lower() == "true" else False
        
        # global toggle: whether to auto-apply deals in cart
        self.auto_apply_deals = True if str(auto_apply_deals).lower() == "true" else False
        
        # Headless logic optimization for VPS
        if headless is None:
            # If not specified, default to HEADLESS on Linux/VPS to prevent crashes
            # On Windows, we can default to headless too for performance, unless debugging
            if platform.system() == "Windows":
                 self.headless = True # Default to headless on Windows too for stability
            else:
                 self.headless = True # Enforce headless on Linux/VPS
        else:
            if isinstance(headless, bool):
                self.headless = headless
            else:
                self.headless = (str(headless).lower() == "true")
        
        self.screenshot_domain = screenshot_domain
        
        print(f"[CONNECT] Headless mode: {self.headless}")

        self.clean_products = {url.strip(): qty for url, qty in products_dict.items()}
        ensure_dirs()
        self.processes = []
        self.stop_requested = False

    def __getstate__(self):
        """
        Exclude live Process objects from pickling (Windows spawn safety).
        """
        state = self.__dict__.copy()
        # Do not attempt to pickle running Process objects
        state["processes"] = []
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        # Recreate empty list for child side; parent maintains its own list
        if "processes" not in self.__dict__ or self.__dict__["processes"] is None:
            self.__dict__["processes"] = []

    def parse_line(self, line):
        email = line.split(",")[0].strip()
        return (
            email,
            self.name or DEFAULT_NAME,
            self.phone or DEFAULT_PHONE,
            self.pincode or DEFAULT_PINCODE,
            self.address1 or DEFAULT_ADDR1,
            self.address2 or DEFAULT_ADDR2,
        )

    # ==========================================================
    # WORKER — FULL MANUAL CONTROLLED PIPELINE
    # ==========================================================
    def _worker(self, index, acc, coupon, use_coupon, q):
        email, name, phone, pin, a1, a2 = acc

        from main import FlipkartSniper, FatalBotError
        import imap as imap_module
        from selenium import webdriver

        # Start immediately; launch staggering is handled in run_all (2s apart)
        delay_seconds = 0
        print(f"⏳ Worker #{index+1} starting immediately (stagger handled by launcher)")
        time.sleep(delay_seconds)

        # Will be assigned just-in-time (after products added)
        popped_coupon = None

        try:
            # Clean up any orphan Chrome processes before starting (Linux VPS optimization)
            # DISABLED: Unsafe in parallel execution (kills other workers' browsers)
            # if platform.system() == "Linux":
            #     kill_orphan_chrome()
            #     time.sleep(0.5)  # Brief pause to ensure cleanup completes
            
            # Create session ID for this worker
            session_id = f"worker_{index}_{int(time.time())}"
            sniper = FlipkartSniper(
                phone_number=email,
                address_data={
                    "name": name,
                    "phone": phone,
                    "pincode": pin,
                    "address_line1": a1,
                    "address_line2": a2,
                },
                products_dict=self.clean_products,
                coupon=coupon,
                max_price=self.max_price,
                deal_keyword=self.deal_keyword,
                auto_apply_deals=self.auto_apply_deals,
                session_id=session_id,
                headless=self.headless,
                allow_less_qty=self.allow_less_qty,
                screenshot_base_url_arg=self.screenshot_domain,
            )

            # ============================
            # DRIVER INITIALIZATION (with retry for VPS stability)
            # ============================
            driver_init_attempts = 0
            max_driver_init_attempts = 3
            driver_initialized = False
            
            while driver_init_attempts < max_driver_init_attempts and not driver_initialized:
                try:
                    driver_init_attempts += 1
                    # Clean up orphan processes before each attempt (Linux VPS)
                    # DISABLED: Unsafe in parallel execution
                    # if platform.system() == "Linux" and driver_init_attempts > 1:
                    #     kill_orphan_chrome()
                    #     time.sleep(1)  # Wait for cleanup
                    
                    # Create driver (same logic as main.py run() method)
                    # Auto-detect using Selenium Manager (no explicit path check needed)
                    sniper.driver = webdriver.Chrome(service=sniper.service, options=sniper.options)
                    sniper.driver.set_page_load_timeout(120)  # Increased to 120s for slow connections
                    sniper.driver.implicitly_wait(10)  # Increased to 10s for slow loading elements
                    
                    # Hide webdriver flag
                    try:
                        sniper.driver.execute_script(
                            "Object.defineProperty(navigator, 'webdriver', {get: () => false});"
                        )
                    except Exception:
                        pass
                    
                    driver_initialized = True
                    print(f"✅ Worker #{index+1} driver initialized successfully (attempt {driver_init_attempts})")
                    
                except Exception as driver_error:
                    if driver_init_attempts >= max_driver_init_attempts:
                        # Final attempt failed, raise error
                        print(f"❌ Worker #{index+1} failed to initialize driver after {max_driver_init_attempts} attempts: {driver_error}")
                        raise FatalBotError(f"DRIVER_INIT_FAILED | NONE")
                    else:
                        # Retry after cleanup
                        print(f"⚠️ Worker #{index+1} driver init attempt {driver_init_attempts} failed, retrying...")
                        try:
                            if sniper.driver:
                                sniper.driver.quit()
                        except:
                            pass
                        sniper.driver = None
                        time.sleep(2)  # Wait before retry
            
            if not driver_initialized:
                raise FatalBotError(f"DRIVER_INIT_FAILED | NONE")

            # ============================
            # EXECUTION PIPELINE
            # ============================

            try:
                # 1) Login
                sniper.step_login(imap_module.otp)

                # 2) Add address
                sniper.step_add_address()
                time.sleep(1)

                # 3) Clear cart
                sniper.step_clear_cart()

                # 4) Add products
                sniper.step_add_all_products()

                # 5) Apply deal booster (ALWAYS - auto-clicks all Add/Apply buttons if no keyword)
                sniper.step_apply_cart_deals(sniper.deal_keyword)

                # 6) Apply coupon (controlled by use_coupon flag) - JIT pop
                if use_coupon:
                    popped_coupon = pop_coupon()
                    if not popped_coupon:
                        raise FatalBotError("NO_COUPON_AVAILABLE | NONE")
                    sniper.coupon = popped_coupon
                    print(f"🏷️ Worker #{index+1} popped coupon: {popped_coupon}")
                    # Mark coupon usage attempt only when popped
                    csv_write(USED_COUPON_FILE, ["coupon", "status"], [popped_coupon, "PENDING"])

                    print(f"\n{'='*60}")
                    print(f"[WORKER DEBUG STEP 7] About to call step_apply_coupon:")
                    print(f"  - use_coupon parameter: {use_coupon}")
                    print(f"  - use_coupon type: {type(use_coupon).__name__}")
                    print(f"  - use_coupon bool check: {bool(use_coupon)}")
                    print(f"  - sniper.coupon: '{sniper.coupon}'")
                    print(f"{'='*60}\n")
                    sniper.step_apply_coupon(use_coupon=use_coupon)

                # 7) Checkout & extract order id
                sniper.step_checkout()
                result = sniper.order_id

            except FatalBotError as fe:
                # _fatal in main.py raises FatalBotError("CODE | URL")
                result = str(fe)

            finally:
                try:
                    if sniper.driver:
                        # Check if driver is still valid before quitting
                        try:
                            # Try a simple operation to check if driver is alive
                            _ = sniper.driver.current_url
                            sniper.driver.quit()
                        except Exception:
                            # Driver is already closed or invalid, just clear reference
                            pass
                        finally:
                            # Always clear reference to prevent double-quit
                            sniper.driver = None
                except Exception:
                    pass

            # ============================
            # HANDLE RESULT
            # ============================
            # Ensure result is never None
            if result is None:
                result = "UNKNOWN_ERROR | NONE"
            
            if isinstance(result, str) and (result.startswith("OD") or result == "OD_SUCCESS_ORDERS_PAGE_OPEN"):
                # SUCCESS
                screenshot_url = getattr(sniper, 'screenshot_url', 'NONE') if sniper else 'NONE'
                if popped_coupon:
                    csv_write(USED_COUPON_FILE, ["coupon", "status"], [popped_coupon, "SUCCESS"])
                    log_success_coupon(popped_coupon, email, result, screenshot_url)
                log_used_mail(email)
                write_success(email, pin, popped_coupon or coupon or "NONE", result, screenshot_url)
                try:
                    q.put({"email": email, "status": "SUCCESS", "order_id": result})
                except Exception as qe:
                    print(f"⚠️ Failed to put success result in queue: {qe}")
                return

            # FAILURE OR FATAL CODE
            error, url = split_error_and_url(result)
            
            # Ensure error and url are strings (safety check)
            if error is None:
                error = "UNKNOWN_ERROR"
            if url is None:
                url = "NONE"
            
            # If error is generic NOT_FOUND but we have a specific fatal code, use that
            if error == "NOT_FOUND" and sniper and sniper.fatal_code:
                error = sniper.fatal_code
            
            screenshot_url = getattr(sniper, 'screenshot_url', url) if sniper else url

            # Special handling: QTY_TOO_LOW → stop all workers immediately
            if error == "QTY_TOO_LOW":
                print(f"[WORKER #{index+1}] Quantity too low - stopping all workers")
                
                # Write failure to CSV before stopping
                coupon_error_codes = {"COUPON_MAX_USAGE_LIMIT", "INVALID_COUPON", "COUPON_EXPIRED", "COUPON_APPLY_ERROR"}
                # QTY_TOO_LOW is not a coupon error, so restore coupon
                if error in CRASH_TYPES or error not in coupon_error_codes:
                    restored = restore_coupon(popped_coupon or coupon)
                    if not restored:
                        print(f"[WORKER #{index+1}] ⚠️ Failed to restore coupon after QTY_TOO_LOW")
                
                # Log coupon usage result to used_coupon.csv (but not to failed_coupon.csv since it's not a coupon error)
                if popped_coupon:
                    csv_write(USED_COUPON_FILE, ["coupon", "status"], [popped_coupon, error])
                elif use_coupon:
                    csv_write(USED_COUPON_FILE, ["coupon", "status"], [coupon or "NONE", error])
                
                # Note: Not logging to failed_coupon.csv since QTY_TOO_LOW is not a coupon error
                
                push_mail_to_bottom(email)
                # #region agent log
                try:
                    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cursor")
                    os.makedirs(log_dir, exist_ok=True)
                    log_path_debug = os.path.join(log_dir, "debug.log")
                    import json
                    with open(log_path_debug, 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"worker","hypothesisId":"RETRY","location":"connect.py:643","message":"QTY_TOO_LOW failed - pushed to bottom","data":{"email":email,"error":error},"timestamp":int(time.time()*1000)}) + "\n")
                except: pass
                # #endregion
                # Always write to failed.csv (contains all failure details)
                write_failure(email, pin, popped_coupon or coupon, error, screenshot_url)
                try:
                    q.put({"email": email, "status": "FAILED"})
                except Exception as qe:
                    print(f"⚠️ Failed to put failure result in queue: {qe}")
                
                self.stop_requested = True
                # Note: Workers can't directly stop other workers in multiprocessing
                # The stop_requested flag will be checked by parent process
                # For immediate effect, we rely on the parent process monitoring
                print(f"[WORKER #{index+1}] QTY_TOO_LOW detected - worker stopping, parent should stop all workers")
                return

            coupon_error_codes = {"COUPON_MAX_USAGE_LIMIT", "INVALID_COUPON", "COUPON_EXPIRED", "COUPON_APPLY_ERROR"}
            is_coupon_error = error in coupon_error_codes

            # Errors for which we NEVER restore the coupon (state unknown / risky to reuse)
            # Include NOT_FOUND to cover cases where result mapping loses the original coupon error
            no_restore_errors = {"DRIVER_UNRESPONSIVE", "NOT_FOUND"}

            # Restore coupon rules:
            # - If it's a coupon error → DON'T restore (coupon stays removed)
            # - If it's in no_restore_errors (e.g. DRIVER_UNRESPONSIVE) → DON'T restore
            # - Otherwise (including CRASH_TYPES) → restore coupon so it can be retried
            if is_coupon_error or error in no_restore_errors:
                print(f"[COUPON] ❌ Coupon '{popped_coupon or coupon}' NOT restored (error: {error}) - coupon remains removed from coupon.txt")
            else:
                restored = restore_coupon(popped_coupon or coupon)
                if restored:
                    print(f"[COUPON] ✅ Restored coupon '{popped_coupon or coupon}' to coupon.txt (error: {error} is not a coupon/no-restore error)")
                else:
                    print(f"[COUPON] ⚠️ FAILED to restore coupon '{popped_coupon or coupon}' to coupon.txt (error: {error})")

            # Log coupon usage result to used_coupon.csv
            if popped_coupon:
                csv_write(USED_COUPON_FILE, ["coupon", "status"], [popped_coupon, error])
            elif use_coupon:
                # If we intended to use coupon but never popped (e.g., fetch failure)
                csv_write(USED_COUPON_FILE, ["coupon", "status"], [coupon or "NONE", error])

            # If it's a coupon error, log to failed_coupon.csv (only coupon and screenshot_url)
            if is_coupon_error and (popped_coupon or (use_coupon and coupon)):
                coupon_to_log = popped_coupon or coupon or "NONE"
                log_failed_coupon(coupon_to_log, email, error, screenshot_url)
                print(f"[COUPON] 📝 Logged coupon error to failed_coupon.csv: {coupon_to_log} (error: {error})")

            push_mail_to_bottom(email)
            # #region agent log
            try:
                log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cursor")
                os.makedirs(log_dir, exist_ok=True)
                log_path_debug = os.path.join(log_dir, "debug.log")
                import json
                with open(log_path_debug, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"worker","hypothesisId":"RETRY","location":"connect.py:669","message":"Failed account - pushed to bottom","data":{"email":email,"error":error},"timestamp":int(time.time()*1000)}) + "\n")
            except: pass
            # #endregion
            # Always write to failed.csv (contains all failure details)
            write_failure(email, pin, popped_coupon or coupon, error, screenshot_url)
            try:
                q.put({"email": email, "status": "FAILED"})
            except Exception as qe:
                print(f"⚠️ Failed to put failure result in queue: {qe}")

        except Exception as e:
            # Hard crash not caught by FatalBotError
            # Simplify crash error to just "CRASH" for failure.csv
            err = "CRASH"
            
            # --- CRITICAL DEBUGGING: Log actual crash reason to file ---
            try:
                import traceback
                crash_log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "crash_details.log")
                timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
                with open(crash_log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[{timestamp}] WORKER #{index+1} CRASHED for account {email}:\n")
                    f.write(f"Error: {str(e)}\n")
                    f.write(traceback.format_exc())
                    f.write("-" * 50 + "\n")
            except:
                pass
            # -----------------------------------------------------------

            screenshot_url = getattr(sniper, 'screenshot_url', 'NONE') if sniper else 'NONE'
            restored = restore_coupon(popped_coupon or coupon)
            if not restored:
                print(f"❌ Failed to restore coupon after CRASH")

            # Log coupon usage result to used_coupon.csv (CRASH is not a coupon error, so don't log to failed_coupon.csv)
            if popped_coupon:
                csv_write(USED_COUPON_FILE, ["coupon", "status"], [popped_coupon, "CRASH"])
            else:
                csv_write(USED_COUPON_FILE, ["coupon", "status"], [coupon or "NONE", "CRASH"])
            
            # Note: Not logging to failed_coupon.csv since CRASH is not a coupon error
            
            push_mail_to_bottom(email)
            # #region agent log
            try:
                log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cursor")
                os.makedirs(log_dir, exist_ok=True)
                log_path_debug = os.path.join(log_dir, "debug.log")
                import json
                with open(log_path_debug, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"worker","hypothesisId":"RETRY","location":"connect.py:704","message":"Exception failed - pushed to bottom","data":{"email":email,"error":err},"timestamp":int(time.time()*1000)}) + "\n")
            except: pass
            # #endregion
            write_failure(email, pin, popped_coupon or coupon, err, screenshot_url)
            print(f"❌ Worker #{index+1} CRASHED: {str(e)[:100] if e else 'Unknown error'}")
            try:
                q.put({"email": email, "status": "FAILED"})
            except Exception as qe:
                print(f"⚠️ Failed to put result in queue: {qe}")

    # ==========================================================
    # CONTROLLER
    # ==========================================================
    def run_all(self):
        # #region agent log
        import json
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cursor")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "debug.log")
        kill_orphan_chrome()
        
        # #region agent log
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"D","location":"connect.py:594","message":"run_all() started, ensuring CSV headers exist","data":{"success_csv":SUCCESS_CSV,"failure_csv":FAILURE_CSV},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        # Ensure CSV files have proper headers (don't clear existing data - preserve history)
        with resource_lock:
            # Only write headers if file doesn't exist (preserve existing data)
            if not os.path.exists(SUCCESS_CSV):
                with open(SUCCESS_CSV, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["email", "postal_code", "order_id", "invoice_image_url"])
            
            if not os.path.exists(FAILURE_CSV):
                with open(FAILURE_CSV, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["email", "postal_code", "coupon", "error", "invoice_image_url"])
            
            # Ensure other CSV files exist
            for f in [SUCCESS_COUPON, FAILED_COUPON, USED_COUPON_FILE]:
                if not os.path.exists(f):
                    open(f, "a").close()

        # Run initial batch
        print(f"\n{'='*60}")
        print(f"[INITIAL RUN] Starting initial batch...")
        print(f"{'='*60}\n")
        
        initial_result = self._run_single_batch()
        # #region agent log
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"B","location":"connect.py:617","message":"Initial batch result","data":{"initial_result":initial_result},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        total_success = initial_result["success_count"]
        total_failed = initial_result["failed_count"]
        total_order_ids = initial_result["order_ids"].copy()
        
        # ==========================================================
        # RETRY FAILED ACCOUNTS (if toggle_retry is enabled)
        # ==========================================================
        if self.toggle_retry and total_failed > 0:
            print(f"\n{'='*60}")
            print(f"[RETRY] Retry enabled. Processing {total_failed} failed account(s)...")
            print(f"{'='*60}\n")
            
            # After initial run, failed emails are at bottom of mail.txt (due to push_mail_to_bottom)
            # Successful ones are moved to used_mail.txt
            # So remaining emails in mail.txt are the failed ones
            retry_mails = load_lines_unique(MAIL_FILE)
            
            # #region agent log
            try:
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"retry","hypothesisId":"RETRY","location":"connect.py:747","message":"Retry check - mail.txt contents","data":{"retry_enabled":self.toggle_retry,"total_failed":total_failed,"retry_mails_count":len(retry_mails),"retry_mails":retry_mails[:10]},"timestamp":int(time.time()*1000)}) + "\n")
            except: pass
            # #endregion
            
            if not retry_mails:
                print("[RETRY] No mails remaining in mail.txt for retry. All may have been moved to used_mail.txt.")
            else:
                print(f"[RETRY] Found {len(retry_mails)} mail(s) remaining in mail.txt to retry")
                print(f"[RETRY] Mails to retry: {retry_mails[:5]}... (showing first 5)")
                
                # mail.txt already contains only failed emails (successful ones moved to used_mail.txt)
                # So we can directly retry all remaining emails
                try:
                    # Run retry batch (mail.txt already has only failed emails)
                    print(f"[RETRY] Starting retry batch with {len(retry_mails)} account(s)...")
                    retry_result = self._run_single_batch()
                    
                    # #region agent log
                    try:
                        with open(log_path, 'a', encoding='utf-8') as f:
                            f.write(json.dumps({"sessionId":"debug-session","runId":"retry","hypothesisId":"RETRY","location":"connect.py:759","message":"After retry batch - mail.txt contents","data":{"retry_mails_after":load_lines_unique(MAIL_FILE)[:10]},"timestamp":int(time.time()*1000)}) + "\n")
                    except: pass
                    # #endregion
                    
                    # Merge results
                    # #region agent log
                    try:
                        with open(log_path, 'a', encoding='utf-8') as f:
                            f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"B","location":"connect.py:647","message":"Retry batch result","data":{"retry_result":retry_result,"initial_success":initial_result["success_count"],"initial_failed":initial_result["failed_count"]},"timestamp":int(time.time()*1000)}) + "\n")
                    except: pass
                    # #endregion
                    total_success = initial_result["success_count"] + retry_result.get("success_count", 0)
                    total_failed = retry_result.get("failed_count", 0)  # Only count remaining failures after retry
                    total_order_ids.extend(retry_result.get("order_ids", []))
                    # #region agent log
                    try:
                        with open(log_path, 'a', encoding='utf-8') as f:
                            f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"B","location":"connect.py:649","message":"Merged totals","data":{"total_success":total_success,"total_failed":total_failed,"total_order_ids_count":len(total_order_ids)},"timestamp":int(time.time()*1000)}) + "\n")
                    except: pass
                    # #endregion
                    
                    print(f"\n{'='*60}")
                    print(f"[RETRY] Retry batch completed.")
                    print(f"[RETRY] Initial Success: {initial_result['success_count']}")
                    print(f"[RETRY] Retry Success: {retry_result.get('success_count', 0)}")
                    print(f"[RETRY] Total Success: {total_success}")
                    print(f"[RETRY] Remaining Failures: {total_failed}")
                    print(f"{'='*60}\n")
                except Exception as e:
                    print(f"[RETRY] ❌ Error during retry: {e}")
                    import traceback
                    traceback.print_exc()
        
        # Return results for app.py to use
        # Aggressive cleanup of Chrome processes for RDP stability
        kill_orphan_chrome()
        time.sleep(1)  # Give processes time to terminate
        kill_orphan_chrome()  # Second pass to catch stragglers
        
        final_result = {
            "success_count": total_success,
            "failed_count": total_failed,
            "order_ids": total_order_ids
        }
        # #region agent log
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"B","location":"connect.py:666","message":"run_all() returning final result","data":{"final_result":final_result},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        return final_result
    
    def _run_single_batch(self):
        """
        Run a single batch of workers (extracted from run_all for retry logic).
        Returns the same result format as run_all.
        """
        self.processes = []
        self.stop_requested = False
        
        mails = load_lines_unique(MAIL_FILE)
        coupons = load_lines_unique(COUPON_FILE) if self.use_coupon else mails

        if not mails:
            print("❌ No mails. Stopping.")
            return {"success_count": 0, "failed_count": 0, "order_ids": []}
        if self.use_coupon and not coupons:
            print("❌ No coupons while coupon usage is enabled. Stopping.")
            return {"success_count": 0, "failed_count": 0, "order_ids": []}

        if self.use_coupon:
            limit = min(len(mails), len(coupons), self.count_limit or 999999)
        else:
            limit = min(len(mails), self.count_limit or 999999)
        print(f"[CONNECT] Computed worker launch limit: {limit} (count_limit={self.count_limit}, mails={len(mails)}, coupons={len(coupons) if self.use_coupon else 'N/A'})")

        accounts = [self.parse_line(m) for m in mails[:limit]]
        # Store current batch emails for later use in counting (to avoid counting historical data)
        current_batch_emails = {acc[0] for acc in accounts}  # Extract emails from current batch
        
        # Track CSV file sizes at start to only count NEW entries written during this run
        # This prevents counting historical failures from previous runs with the same emails
        initial_success_lines = 0
        initial_failure_lines = 0
        if os.path.exists(SUCCESS_CSV):
            try:
                with open(SUCCESS_CSV, 'r', encoding='utf-8') as f:
                    initial_success_lines = len(f.readlines())
            except:
                pass
        if os.path.exists(FAILURE_CSV):
            try:
                with open(FAILURE_CSV, 'r', encoding='utf-8') as f:
                    initial_failure_lines = len(f.readlines())
            except:
                pass

        q = Queue()
        processes = self.processes

        print(f"▶ Launching {limit} workers... (8s stagger enabled, max_parallel={self.max_parallel})")

        for i in range(limit):
            if self.stop_requested:
                print("[CONNECT] Stop requested before launching remaining workers. Halting launches.")
                break
            acc = accounts[i]
            coupon = None  # Will be popped just-in-time inside worker

            # Stagger launches: first immediately, then every 5s (increased for RDP stability)
            if i > 0:
                time.sleep(5)

            # Limit parallelism with longer wait time for resource stability
            while len([p for p in processes if p.is_alive()]) >= self.max_parallel:
                if self.stop_requested:
                    print("[CONNECT] Stop requested during parallel wait. Halting further launches.")
                    break
                time.sleep(1.0)  # Increased from 0.2s to 1s for better resource management
            if self.stop_requested:
                break

            print(f"[CONNECT DEBUG STEP 6] Launching worker #{i+1}:")
            print(f"  - Passing use_coupon to worker: {self.use_coupon}")
            print(f"  - use_coupon type: {type(self.use_coupon).__name__}")
            print(f"  - Coupon code (JIT): {coupon}\n")
            p = Process(target=self._worker, args=(i, acc, coupon, self.use_coupon, q))
            p.start()
            processes.append(p)

        # Wait for all workers, but check for early termination signals
        while any(p.is_alive() for p in processes):
            if self.stop_requested:
                print("[CONNECT] Stop requested during worker wait - terminating remaining workers")
                for p in processes:
                    if p.is_alive():
                        try:
                            p.terminate()
                            p.join(timeout=2)
                        except Exception:
                            pass
                break
            # Don't consume queue items here - they'll be collected after all workers finish
            # Just check if we should stop (but don't read from queue)
            time.sleep(0.5)
        
        # Final join for any remaining processes - wait longer to ensure they finish
        for p in processes:
            if p.is_alive():
                p.join(timeout=5)  # Increased timeout to 5 seconds

        # Double-check all processes are dead
        still_alive = [p for p in processes if p.is_alive()]
        if still_alive:
            print(f"⚠️ WARNING: {len(still_alive)} worker(s) still alive after join, forcing termination")
            for p in still_alive:
                try:
                    p.terminate()
                    p.join(timeout=2)
                except:
                    pass

        # Wait a bit more to ensure all workers have written to queue/CSV
        # This is especially important if workers crashed but wrote to CSV
        time.sleep(2.0)  # Increased to 2 seconds

        # Gather results safely - read ALL items from queue
        result_list = []
        # Read multiple times to ensure we get all items (queue might have items added during reading)
        for _ in range(100):  # Max 100 iterations to prevent infinite loop
            items_read = 0
            while not q.empty():
                try:
                    item = q.get_nowait()
                    if isinstance(item, dict):
                        result_list.append(item)
                        items_read += 1
                except Exception:
                    break
            if items_read == 0:
                break  # No more items to read
            time.sleep(0.1)  # Small delay to allow more items to be added

        success_items = [r for r in result_list if r.get("status") == "SUCCESS"]
        failed_items = [r for r in result_list if r.get("status") != "SUCCESS"]
        
        # #region agent log
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"B","location":"connect.py:836","message":"Queue results gathered","data":{"result_list_count":len(result_list),"success_items_count":len(success_items),"failed_items_count":len(failed_items),"result_list":result_list},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        
        # Count from CSV files (source of truth) instead of queue to avoid missing results
        csv_success_count = 0
        csv_failed_count = 0
        if os.path.exists(SUCCESS_CSV):
            try:
                with open(SUCCESS_CSV, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    csv_success_count = len(list(reader))
            except:
                try:
                    with open(SUCCESS_CSV, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        csv_success_count = len(lines) - 1 if len(lines) > 1 else 0
                except:
                    pass
        
        if os.path.exists(FAILURE_CSV):
            try:
                with open(FAILURE_CSV, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    csv_failed_count = len(list(reader))
            except:
                try:
                    with open(FAILURE_CSV, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        csv_failed_count = len(lines) - 1 if len(lines) > 1 else 0
                except:
                    pass
        
        # #region agent log
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"B","location":"connect.py:860","message":"CSV counts vs Queue counts","data":{"csv_success":csv_success_count,"csv_failed":csv_failed_count,"queue_success":len(success_items),"queue_failed":len(failed_items)},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        
        # Extract used emails from CSV file (source of truth) for mail removal
        used_emails_from_queue = [r.get("email") for r in success_items if r.get("email")]
        used_emails_from_csv = []
        if os.path.exists(SUCCESS_CSV):
            try:
                with open(SUCCESS_CSV, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        email = row.get('email', '').strip()
                        if email:
                            used_emails_from_csv.append(email)
            except:
                try:
                    with open(SUCCESS_CSV, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        if len(lines) > 1:
                            for line in lines[1:]:
                                parts = line.strip().split(',')
                                if len(parts) > 0:
                                    email = parts[0].strip().strip('"').strip("'")
                                    if email:
                                        used_emails_from_csv.append(email)
                except:
                    pass
        
        # Use CSV emails as source of truth, fallback to queue if CSV fails
        used_emails = used_emails_from_csv if used_emails_from_csv else used_emails_from_queue
        
        # #region agent log
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"E","location":"connect.py:880","message":"Used emails for removal","data":{"from_csv":used_emails_from_csv,"from_queue":used_emails_from_queue,"final":used_emails},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        
        # If CSV has more successes than queue, we're missing queue items - log warning
        # Note: We'll filter by current batch emails when using CSV fallback, so these warnings are informational
        if csv_success_count > len(success_items):
            print(f"⚠️ WARNING: CSV shows {csv_success_count} successes but queue only has {len(success_items)}. Will filter by current batch if using CSV.")
        if csv_failed_count > len(failed_items):
            print(f"⚠️ WARNING: CSV shows {csv_failed_count} failures but queue only has {len(failed_items)}. Will filter by current batch if using CSV.")

        # Handle successful mails based on toggle
        # #region agent log
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"E","location":"connect.py:775","message":"Before mail handling","data":{"remove_mail_on_success":self.remove_mail_on_success,"used_emails_count":len(used_emails),"used_emails":used_emails[:5],"success_count":len(success_items),"failed_count":len(failed_items)},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        if self.remove_mail_on_success:
            # Remove from mail.txt and move to used_mail.txt
            # #region agent log
            try:
                with open(log_path, 'a', encoding='utf-8') as f:
                    mails_before_removal = load_lines_unique(MAIL_FILE)
                    f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"RETRY","location":"connect.py:996","message":"Before removing successful emails","data":{"mails_before":mails_before_removal[:10],"used_emails":used_emails},"timestamp":int(time.time()*1000)}) + "\n")
            except: pass
            # #endregion
            save_used_lines(used_emails, MAIL_FILE, USED_MAIL_FILE)
            # #region agent log
            try:
                with open(log_path, 'a', encoding='utf-8') as f:
                    mails_after_removal = load_lines_unique(MAIL_FILE)
                    f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"RETRY","location":"connect.py:1002","message":"After save_used_lines (removed from mail.txt)","data":{"mails_after":mails_after_removal[:10],"removed_emails":used_emails},"timestamp":int(time.time()*1000)}) + "\n")
            except: pass
            # #endregion
        else:
            # Append successful mails back to mail.txt
            with resource_lock:
                with open(MAIL_FILE, "a", encoding="utf-8") as f:
                    for email in used_emails:
                        f.write(email + "\n")
                # Still log to used_mail.txt for tracking
                with open(USED_MAIL_FILE, "a", encoding="utf-8") as f:
                    for email in used_emails:
                        f.write(email + "\n")

        # Collect order IDs: prioritize queue, but always fallback to CSV if queue is incomplete
        order_ids = []
        order_ids_from_queue = []
        for item in success_items:
            order_id = item.get("order_id", "")
            if order_id and (order_id.startswith('OD') or order_id.startswith('od') or order_id == "OD_SUCCESS_ORDERS_PAGE_OPEN"):
                if order_id not in order_ids_from_queue:  # Avoid duplicates
                    order_ids_from_queue.append(order_id)
        
        # Always read from CSV to get complete order IDs (CSV is source of truth)
        if os.path.exists(SUCCESS_CSV):
            try:
                with open(SUCCESS_CSV, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    # Get all order IDs from CSV (for current run's success emails if available, otherwise all)
                    if success_items:
                        success_emails = {item.get("email", "").strip() for item in success_items if item.get("email")}
                        for row in reversed(rows):  # Read from bottom to get most recent
                            row_email = (row.get('email', '') or row.get('Email', '') or 
                                        row.get('EMAIL', '')).strip()
                            if row_email in success_emails:
                                order_id = (row.get('order_id', '') or row.get('Order ID', '') or 
                                           row.get('orderId', '') or row.get('ORDER_ID', '') or
                                           row.get('order id', '') or row.get('OrderId', '')).strip()
                                if order_id and (order_id.startswith('OD') or order_id.startswith('od')):
                                    if order_id not in order_ids:
                                        order_ids.append(order_id)
                    else:
                        # No queue items, read all order IDs from CSV
                        for row in rows:
                            order_id = (row.get('order_id', '') or row.get('Order ID', '') or 
                                       row.get('orderId', '') or row.get('ORDER_ID', '') or
                                       row.get('order id', '') or row.get('OrderId', '')).strip()
                            if order_id and (order_id.startswith('OD') or order_id.startswith('od')):
                                if order_id not in order_ids:
                                    order_ids.append(order_id)
            except Exception:
                pass
        
        # If we got order IDs from queue but not from CSV, use queue ones
        if not order_ids and order_ids_from_queue:
            order_ids = order_ids_from_queue

        # Use queue counts as primary (current run only), CSV as fallback only if queue is empty
        # This ensures we only count current run's results, not historical data
        if len(success_items) > 0 or len(failed_items) > 0:
            # Queue has data from current run - use it
            final_success_count = len(success_items)
            final_failed_count = len(failed_items)
        else:
            # Queue is empty (workers crashed before putting results) - use CSV but only count NEW entries
            # Count only entries that were written DURING this run (after initial line counts)
            # This prevents counting historical failures from previous runs with the same emails
            final_success_count = 0
            final_failed_count = 0
            
            # Count NEW successes written during this run (lines added after initial count)
            if os.path.exists(SUCCESS_CSV):
                try:
                    with open(SUCCESS_CSV, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        # Skip header (line 0) and initial lines, count only new lines
                        # initial_success_lines includes header, so new lines start from that index
                        new_lines = lines[initial_success_lines:] if initial_success_lines > 0 else lines[1:]
                        for line in new_lines:
                            if line.strip():  # Skip empty lines
                                final_success_count += 1
                except:
                    pass
            
            # Count NEW failures written during this run (lines added after initial count)
            # This is the correct way - only count failures written during THIS batch run
            if os.path.exists(FAILURE_CSV):
                try:
                    with open(FAILURE_CSV, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        # Skip header (line 0) and initial lines, count only new lines written during this run
                        # initial_failure_lines includes header, so new lines start from that index
                        new_lines = lines[initial_failure_lines:] if initial_failure_lines > 0 else lines[1:]
                        new_failure_emails = []
                        for line in new_lines:
                            if line.strip():  # Skip empty lines
                                final_failed_count += 1
                                # Also extract email for debug
                                try:
                                    parts = line.strip().split(',')
                                    if len(parts) > 0:
                                        email = parts[0].strip().strip('"').strip("'")
                                        if email:
                                            new_failure_emails.append(email)
                                except:
                                    pass
                        # Debug: show what we're counting
                        if len(new_failure_emails) > 0:
                            print(f"   [DEBUG] Found {len(new_failure_emails)} NEW failures written during this run (from line {initial_failure_lines} onwards)")
                            print(f"   [DEBUG] New failure emails: {new_failure_emails}")
                        elif initial_failure_lines > 0:
                            print(f"   [DEBUG] No new failures written during this run (CSV had {initial_failure_lines} lines at start)")
                except Exception as e:
                    print(f"   [DEBUG] Error reading FAILURE_CSV: {e}")
                    pass
        
        # Debug output when queue is empty to verify filtering
        if len(success_items) == 0 and len(failed_items) == 0:
            print(f"   [DEBUG] Queue empty - filtering CSV by current batch emails: {sorted(current_batch_emails)}")
            print(f"   [DEBUG] Filtered counts - Success: {final_success_count}, Failure: {final_failed_count} (from {csv_success_count} total success, {csv_failed_count} total failure in CSV)")
        
        # Debug output when queue is empty to verify filtering is working
        if len(success_items) == 0 and len(failed_items) == 0 and (csv_success_count > 0 or csv_failed_count > 0):
            print(f"   [DEBUG] Queue empty - filtering CSV by current batch emails: {sorted(current_batch_emails)}")
            print(f"   [DEBUG] Filtered counts - Success: {final_success_count}, Failure: {final_failed_count} (from {csv_success_count} total success, {csv_failed_count} total failure in CSV)")
        
        print(f"✔ Done. Success={final_success_count} (CSV:{csv_success_count}, Queue:{len(success_items)}) Failure={final_failed_count} (CSV:{csv_failed_count}, Queue:{len(failed_items)}) OrderIDs={len(order_ids)}")
        
        batch_result = {
            "success_count": final_success_count,
            "failed_count": final_failed_count,
            "order_ids": order_ids
        }
        # #region agent log
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"connect","hypothesisId":"B","location":"connect.py:821","message":"_run_single_batch() returning result","data":{"batch_result":batch_result,"success_items_count":len(success_items),"failed_items_count":len(failed_items)},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        return batch_result

    def stop_workers(self, count):
        """
        Terminate up to `count` running worker processes.
        Returns number of workers actually terminated.
        """
        # Prevent launching new workers in this run
        self.stop_requested = True
        stopped = 0
        for p in list(self.processes):
            if stopped >= count:
                break
            if p.is_alive():
                try:
                    p.terminate()
                    p.join(timeout=5)
                    if p.is_alive() and hasattr(p, "kill"):
                        p.kill()
                        p.join(timeout=2)
                    stopped += 1
                except Exception:
                    continue
        # Optionally prune terminated processes from the list
        self.processes = [p for p in self.processes if p.is_alive()]
        # Best-effort cleanup of any orphaned Chrome processes
        kill_orphan_chrome()
        restore_pending_coupons_on_stop()
        return stopped

    def stop_all_workers(self):
        """
        Terminate all running worker processes immediately.
        Returns number of workers actually terminated.
        """
        self.stop_requested = True
        alive = [p for p in self.processes if p.is_alive()]
        
        # 1. Send SIGTERM to all simultaneousy
        for p in alive:
            try:
                p.terminate()
            except Exception:
                pass
        
        # 2. Wait up to 5s for ALL to finish (parallel wait)
        start_wait = time.time()
        while time.time() - start_wait < 5:
            if not any(p.is_alive() for p in alive):
                break
            time.sleep(0.1)
            
        # 3. Force kill any stragglers
        stopped = 0
        for p in alive:
            if p.is_alive():
                try:
                    if hasattr(p, "kill"):
                        p.kill()
                        p.join(timeout=1) # Short wait for kill
                except:
                    pass
            stopped += 1

        # prune list
        self.processes = [p for p in self.processes if p.is_alive()]
        
        # Best-effort cleanup (only run if we actually stopped something or if requested)
        # Note: kill_orphan_chrome might be dangerous if other bots are running, 
        # but stop_all_workers implies stopping everything.
        kill_orphan_chrome()
        restore_pending_coupons_on_stop()
        return stopped
