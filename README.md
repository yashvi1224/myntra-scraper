# Myntra Product Scraper

A tool that takes a list of Myntra product IDs and fetches structured product details from public Myntra pages.

---

## How to Run

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2a. CLI — scrape directly to JSON

```bash
python backend/scraper.py sample_products.csv --output output/results.json

# With bonus delivery check:
python backend/scraper.py sample_products.csv --output output/results.json --delivery
```

### 2b. Web UI — run the Flask server

```bash
python backend/api.py
# Then open http://localhost:5000 in your browser
```

Upload the CSV, optionally toggle delivery check, click **Scrape Products**.

---

## Output Format

Each product produces a JSON object:

```json
{
  "product_id":    "2338558",
  "url":           "https://www.myntra.com/2338558/buy",
  "title":         "HERE&NOW Women Red & White Striped T-shirt",
  "description":   "Cotton T-shirt, round neck...",
  "images":        ["https://assets.myntassets.com/..."],
  "rating":        "4.2",
  "total_ratings": "3412",
  "category":      "T-Shirts",
  "category_ads": [
    { "title": "MANGO Women Striped T-shirt", "price": "Rs. 2999", "rating": "4.1", "sponsored": true }
  ],
  "delivery": {
    "Bengaluru": "Get it by Tomorrow",
    "Mumbai":    "Get it by Tomorrow"
  },
  "errors":      [],
  "scraped_at":  "2024-09-05T10:32:11Z"
}
```

See `output/sample_output.json` for a full example including a failed/unavailable product.

---

## Approach & Why

### Headless browser (Playwright)

Myntra renders entirely in JavaScript — `requests` + `BeautifulSoup` returns an empty shell.  
Playwright drives a real Chromium instance, waits for JS hydration, and extracts DOM elements.

### Anti-detection measures
- Removes the `navigator.webdriver` flag via `add_init_script`
- Sets a real-looking User-Agent
- Random delays between requests (1.5–3.5 s) to avoid rate limiting
- No session sharing between products (new page per request, same context)

### Robustness
- Every field is wrapped in its own `try/except`; a missing field never crashes the run
- Errors are collected per product in the `errors` array
- Results are written to disk **incrementally** — a mid-run crash doesn't lose completed products
- Missing data fields are `null` (not omitted), so consumers always see the same schema

### Category ads
- Constructs a search URL from the product's category breadcrumb
- Scans product cards for a sponsored/ad label
- Stops after 3 ad results; skips organic results entirely

### Delivery check (bonus)
- Enters each pincode into the delivery estimator widget on the product page
- Captures the resulting delivery estimate text
- Covered cities: Bengaluru, Mumbai, Delhi, Ahmedabad, Kolkata

---

## Assumptions

1. Product URLs follow the pattern `myntra.com/{product_id}/buy`
2. CSS class names for sponsored labels are `sponsored`, `Sponsored`, or similar — Myntra obfuscates these and they may change; the selector uses a case-insensitive text match as a fallback
3. The delivery widget exists on the product page; if Myntra A/B tests it away, delivery returns `"pincode input not found"`
4. One image per HTTP round-trip is acceptable; the tool does not parallelize to avoid triggering bot detection

---

## Scoped In vs. Out

### In
- All core fields: title, description, images (up to 2), rating, rating count, category
- First 3 sponsored category results with price and rating
- Graceful error handling with partial results
- JSON output (incremental)
- Web frontend (Flask + vanilla JS)
- Bonus: delivery estimates for 5 city pincodes

### Out (would build next with more time)
- **Proxy rotation** — currently relies on natural delays; a pool of residential proxies would make large batches reliable
- **Parallel scraping** — sequential is safe but slow; async task pool with concurrency=3 would be ~3× faster
- **Retries with exponential backoff** — a single failed page is currently skipped; retrying after a short wait would recover transient blocks
- **CAPTCHA handling** — Myntra occasionally serves a CAPTCHA; detecting and pausing/alerting would be needed for large runs
- **Schema versioning** — Myntra's markup changes; adding a schema version field to output helps consumers detect staleness
- **Database sink** — writing to SQLite or Postgres instead of a flat JSON file for easier querying

---

## Known Limitations

- Myntra's class names are obfuscated and **will change**; selectors will need updating periodically
- Large batches (50+ products) risk IP blocks without proxies
- The delivery widget sometimes requires a page interaction before the pincode input appears; the current implementation attempts it but may miss it on first load

---

## Project Structure

```
myntra-scraper/
├── backend/
│   ├── scraper.py      # Core Playwright scraper
│   └── api.py          # Flask API wrapping the scraper
├── frontend/
│   └── index.html      # Single-page UI
├── output/
│   └── sample_output.json
├── sample_products.csv
├── requirements.txt
└── README.md
```
