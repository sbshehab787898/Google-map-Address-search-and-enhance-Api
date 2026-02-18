# Google Maps Verification API (Scraper Edition)

This API uses **Selenium** to browse the real Google Maps website and search for an address. It tells you if the address is "Real" (found as a specific place) or "Fake" (no results) and extracts the corrected address details.

**WARNING:** This method is slower than an API (takes 5-10 seconds per request) but is **free** and uses **real Google Maps data**.

## Setup Instructions

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Run Locally**:
    ```bash
    python app.py
    ```
    *Note: The first time you run this, it will download the Chrome Driver automatically.*

## Usage

**Endpoint:** `POST /enhance`

**Body:**
```json
{
  "address": "Dhanmondi 32"
}
```

**Response (Real Address):**
```json
{
  "status": "success",
  "verification": "real",
  "data": {
    "place_name": "Bangabandhu Memorial Museum",
    "full_address": "Road No. 32, Dhaka 1205, Bangladesh",
    "components": {
      "city": "Dhaka",
      "zip_code": "1205",
      "country": "Bangladesh"
    }
  }
}
```

**Response (Fake Address):**
```json
{
  "status": "fake",
  "verification": "fake",
  "message": "Google Maps explicitly returned no results."
}
```

## Deployment Note (Render)
Deploying Selenium to Render requires a specific Docker environment or Build Pack. For now, this is best run on your **local machine** or a VPS.
