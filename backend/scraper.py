"""
Myntra Product Scraper — Selenium + BeautifulSoup
Uses webdriver-manager to auto-match ChromeDriver to your Chrome version.
"""

import time
import random
import json
import csv
import re
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import requests


# ─── Constants ───────────────────────────────────────────────────────────────

BASE_URL = "https://www.myntra.com"

PINCODES = {
    "Bengaluru": "560001",
    "Mumbai":    "400001",
    "Delhi":     "110001",
    "Ahmedabad": "380001",
    "Kolkata":   "700001",
}

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}


def jitter(lo=2.0, hi=5.0):
    time.sleep(random.uniform(lo, hi))


# ─── Driver setup ────────────────────────────────────────────────────────────

def make_driver(headless=True) -> webdriver.Chrome:
    """
    webdriver-manager automatically downloads the correct ChromeDriver
    for whatever Chrome version you have installed.
    """
    options = Options()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=en-IN")
    options.add_argument("--window-size=1440,900")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument(
        f"user-agent={HEADERS['User-Agent']}"
    )

    # Hide automation flags
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # webdriver-manager picks the right driver version automatically
    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=options)

    # Patch navigator.webdriver to undefined
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins',   { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-IN','en-US','en'] });
            window.chrome = { runtime: {} };
        """
    })

    return driver


# ─── HTML helpers ────────────────────────────────────────────────────────────

def get_soup(driver) -> BeautifulSoup:
    return BeautifulSoup(driver.page_source, "html.parser")


def text_or_none(tag) -> Optional[str]:
    return tag.get_text(strip=True) if tag else None


# ─── Product scraper ─────────────────────────────────────────────────────────

def scrape_product(driver, product_id: str, delivery_check=False) -> dict:
    url = f"{BASE_URL}/{product_id}"
    result = {
        "product_id":    product_id,
        "url":           url,
        "title":         None,
        "description":   None,
        "images":        [],
        "rating":        None,
        "total_ratings": None,
        "category":      None,
        "category_ads":  [],
        "delivery":      {},
        "errors":        [],
        "scraped_at":    datetime.utcnow().isoformat() + "Z",
    }

    # ── Load page ──
    try:
        driver.get(url)
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CLASS_NAME, "pdp-title"))
        )
        jitter(2, 4)
    except TimeoutException:
        result["errors"].append("page_load: timed out — product may be unavailable or blocked")
        return result
    except Exception as e:
        result["errors"].append(f"page_load: {e}")
        return result

    soup = get_soup(driver)

    # ── Title ──
    try:
        brand = soup.select_one(".pdp-title")
        name  = soup.select_one(".pdp-name")
        if brand and name:
            result["title"] = f"{brand.get_text(strip=True)} {name.get_text(strip=True)}"
        elif brand:
            result["title"] = brand.get_text(strip=True)
        else:
            result["title"] = driver.title
    except Exception as e:
        result["errors"].append(f"title: {e}")

    # ── Description ──
    try:
        try:
            desc_btn = driver.find_element(By.XPATH, "//*[contains(text(),'Product Description')]")
            desc_btn.click()
            time.sleep(0.8)
            soup = get_soup(driver)
        except NoSuchElementException:
            pass

        desc = soup.select_one(".pdp-description-content") or soup.select_one(".index-sizeFitDesc")
        result["description"] = text_or_none(desc)
    except Exception as e:
        result["errors"].append(f"description: {e}")

    # ── Images (up to 2) ──
    try:
        for sel in [".image-grid-image", ".pdp-imageContainer img", "img.img-responsive"]:
            imgs = soup.select(sel)
            if imgs:
                for tag in imgs[:2]:
                    src = tag.get("src") or tag.get("data-src") or ""
                    if src.startswith("http"):
                        result["images"].append(src)
                        continue                          # ← found it, skip step 2

                    # 2. <div style="background-image: url('...')"> tag  (Myntra's way)
                    style = tag.get("style", "")
                    match = re.search(r'url\(["\']?(https?://[^"\')\s]+)["\']?\)', style)
                    if match:
                        result["images"].append(match.group(1))
                if result["images"]:
                    break
    except Exception as e:
        result["errors"].append(f"images: {e}")

    # ── Rating ──
    try:
        for sel in [".index-overallRating span", ".detailed-reviews-productRating span"]:
            tag = soup.select_one(sel)
            if tag:
                result["rating"] = tag.get_text(strip=True)
                break
    except Exception as e:
        result["errors"].append(f"rating: {e}")

    # ── Total ratings ──
    try:
        for sel in [".index-ratingsCount", "[class*='ratingsCount']"]:
            tag = soup.select_one(sel)
            if tag:
                txt  = tag.get_text(strip=True)
                nums = re.findall(r"[\d,]+", txt)
                result["total_ratings"] = nums[0].replace(",", "") if nums else txt
                break
    except Exception as e:
        result["errors"].append(f"total_ratings: {e}")

    # ── Category (breadcrumb) ──
    try:
        crumbs = soup.select(".breadcrumbs-list li a")
        if crumbs:
            result["category"] = crumbs[-1].get_text(strip=True)
    except Exception as e:
        result["errors"].append(f"category: {e}")

    # ── Category ads ──
    if result["category"]:
        try:
            result["category_ads"] = scrape_category_ads(driver, result["category"])
        except Exception as e:
            result["errors"].append(f"category_ads: {e}")
    # ── Delivery (bonus) ──
    if delivery_check:
        try:
            result["delivery"] = check_delivery(driver, product_id)
        except Exception as e:
            result["errors"].append(f"delivery: {e}")

    jitter(2, 4)
    return result


# ─── Category ads ────────────────────────────────────────────────────────────

def scrape_category_ads(driver, category: str) -> list:
    query      = category.lower().replace(" ", "-")
    search_url = f"{BASE_URL}/{query}"
    ads        = []

    try:
        driver.get(search_url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, "product-base"))
        )
        jitter(2, 3)
    except Exception:
        return ads

    soup  = get_soup(driver)
    cards = soup.select(".product-base")

    for card in cards:
        if len(ads) >= 3:
            break

        text_lower   = card.get_text().lower()
        is_sponsored = (
            card.select_one("[class*='sponsored']")
            or card.select_one("[class*='Sponsored']")
            or card.select_one("[class*='ad-tag']")
            or "sponsored" in text_lower
        )
        if not is_sponsored:
            continue

        try:
            brand   = text_or_none(card.select_one(".product-brand"))
            product = text_or_none(card.select_one(".product-product"))
            title   = " ".join(filter(None, [brand, product])) or None
            price   = (
                text_or_none(card.select_one(".product-discountedPrice"))
                or text_or_none(card.select_one(".product-price span"))
            )
            rating  = (
                text_or_none(card.select_one(".product-ratingsCount"))
                or text_or_none(card.select_one(".product-rating span"))
            )
            ads.append({"title": title, "price": price, "rating": rating, "sponsored": True})
        except Exception:
            continue

    jitter(1.5, 3)
    return ads


# ─── Delivery check ──────────────────────────────────────────────────────────

def check_delivery(driver, product_id):
    """
    Checks delivery for all PINCODES on Myntra.
    Scrolls to form .pincode-deliveryContainer, fills each pincode one by one,
    clicks the Check button, and parses deliveryInfo / eta / deliveryDate.

    Returns a list of dicts:
      [{ city, pincode, deliveryInfo, eta, deliveryDate }, ...]
    """
    wait             = WebDriverWait(driver, 10)
    delivery_results = []

    # ── Gradual scroll down to reveal the pincode section ───────────────────
    # Myntra lazy-loads the delivery widget; scrolling naturally triggers it.
    total_height = driver.execute_script("return document.body.scrollHeight")
    current_pos  = 0
    step         = 300          # pixels per scroll step

    while current_pos < total_height:
        current_pos += step
        driver.execute_script(f"window.scrollTo({{top: {current_pos}, behavior: 'smooth'}});")
        time.sleep(0.3)

        # Stop early once the container is in the DOM — no need to scroll further
        try:
            driver.find_element(By.CSS_SELECTOR, "div .pincode-deliveryContainer")
            break
        except Exception:
            pass

    time.sleep(0.8)   # let final scroll settle

    for city, pincode in PINCODES.items():
        try:
            # ── 1. Wait for container inside <form> ──────────────────────────
            container = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div .pincode-deliveryContainer")
                )
            )

            # ── 2. Scroll smoothly to the container ─────────────────────────
            driver.execute_script(
                "arguments[0].scrollIntoView({behavior:'smooth', block:'center'});",
                container
            )
            time.sleep(0.8)

            # ── 3. If "Change" button is visible, click it to reset input ────
            #    Myntra shows this after a pincode has already been checked.
            #    Clicking it clears the result and re-shows the input field.
            try:
                change_btn = driver.find_element(
                    By.CSS_SELECTOR,
                    "button.pincode-check-another-pincode.pincode-button"
                )
                if change_btn.is_displayed():
                    driver.execute_script("arguments[0].click();", change_btn)
                    time.sleep(0.8)   # wait for input to re-appear
            except Exception:
                pass   # first pincode — Change button won't exist yet

            # ── 4. Clear & type pincode into the input ───────────────────────
            pincode_input = wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR,
                     "div .pincode-deliveryContainer input:not([type='submit'])")
                )
            )
            pincode_input.clear()
            time.sleep(0.3)
            pincode_input.send_keys(pincode)
            time.sleep(0.3)

            # ── 5. Click the Check button ────────────────────────────────────
            check_btn = container.find_element(
                By.CSS_SELECTOR, "input.pincode-check.pincode-button"
            )
            driver.execute_script("arguments[0].click();", check_btn)

            # ── 6. Wait for the result section to appear ─────────────────────
            #    Myntra renders result inside .pincode-serviceability or
            #    .pincode-deliveryInfo after the API responds (~1-2 s)
            time.sleep(2.0)

            # ── 7. Re-fetch container (DOM may have re-rendered) ─────────────
            container = driver.find_element(
                By.CSS_SELECTOR, "div .pincode-deliveryContainer"
            )

            # ── 8. Extract fields ────────────────────────────────────────────
            info = extract_delivery_info(driver, container)

            # ── 9. Guard: skip silently if nothing was found ─────────────────
            if all(v is None for v in info.values()):
                print(f"  [WARN] {city} ({pincode}): no delivery info found — skipping")
                delivery_results.append({
                    "city":         city,
                    "pincode":      pincode,
                    "deliveryInfo": None,
                    "eta":          None,
                    "deliveryDate": None,
                    "status":       "not_found",
                })
            else:
                delivery_results.append({
                    "city":         city,
                    "pincode":      pincode,
                    "deliveryInfo": info["deliveryInfo"],
                    "eta":          info["eta"],
                    "deliveryDate": info["deliveryDate"],
                    "status":       "ok",
                })

        except Exception as e:
            print(f"  [ERROR] {city} ({pincode}): {e}")
            delivery_results.append({
                "city":         city,
                "pincode":      pincode,
                "deliveryInfo": None,
                "eta":          None,
                "deliveryDate": None,
                "status":       "error",
                "error":        str(e),
            })

        jitter(1.0, 2.0)   # polite delay between pincode checks

    return delivery_results


def extract_delivery_info(driver, container):
    """
    Extracts delivery info from Myntra's actual DOM element:
      span.SelectedSizeSellerInfo-deliveryMessage
      Raw text example: "Get it by Sun, Jun 28"

    Parses into:
      deliveryInfo  → full raw text  e.g. "Get it by Sun, Jun 28"
      deliveryDate  → date part only e.g. "Sun, Jun 28"
      eta           → day name only  e.g. "Sun"
    """
    result = {
        "deliveryInfo": None,
        "eta":          None,
        "deliveryDate": None,
    }

    try:
        # ── Primary: confirmed Myntra selector ──────────────────────────────
        el   = driver.find_element(By.CSS_SELECTOR, "span.SelectedSizeSellerInfo-deliveryMessage")
        text = el.text.strip()

        if text:
            result["deliveryInfo"] = text          # "Get it by Sun, Jun 28"

            # Parse "Get it by <Day>, <Month> <Date>"
            # e.g. "Get it by Sun, Jun 28"  →  date_part = "Sun, Jun 28"
            match = re.search(r"Get it by (.+)", text, re.IGNORECASE)
            if match:
                date_part = match.group(1).strip()     # "Sun, Jun 28"
                result["deliveryDate"] = date_part

                # eta = day name before the comma  e.g. "Sun"
                eta_match = re.match(r"(\w+),", date_part)
                if eta_match:
                    result["eta"] = eta_match.group(1)  # "Sun"

    except Exception:
        # ── Fallback: raw container text ────────────────────────────────────
        try:
            raw = container.text.strip()
            if raw:
                result["deliveryInfo"] = raw
        except Exception:
            pass

    return result




# ─── Orchestrator ────────────────────────────────────────────────────────────

def run(input_csv: str, output_json: str, delivery_check=False, headless=True):
    product_ids = []
    with open(input_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = (
                row.get("product_id")
                or row.get("Product ID")
                or row.get("productId")
                or list(row.values())[0]
            )
            if pid and str(pid).strip():
                product_ids.append(str(pid).strip())

    print(f"[INFO] {len(product_ids)} product IDs loaded.")
    print("[INFO] Auto-downloading matching ChromeDriver …")

    driver  = make_driver(headless=headless)
    results = []
    out     = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        for i, pid in enumerate(product_ids, 1):
            print(f"[{i}/{len(product_ids)}] Scraping {pid} …", flush=True)
            data = scrape_product(driver, pid, delivery_check=delivery_check)
            results.append(data)

            icon = "✓" if not data["errors"] else f"⚠ {len(data['errors'])} error(s)"
            print(f"  {icon} — {data['title'] or 'no title'}")
            for err in data["errors"]:
                print(f"    • {err}")

            out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        driver.quit()

    print(f"\n[DONE] Results → {output_json}")
    return results


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("input_csv")
    p.add_argument("--output",   default="output/results.json")
    p.add_argument("--delivery", action="store_true")
    p.add_argument("--visible",  action="store_true", help="Show browser window")
    args = p.parse_args()

    run(args.input_csv, args.output,
        delivery_check=args.delivery,
        headless=not args.visible)