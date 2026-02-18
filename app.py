import os
import re
import time
import urllib.parse
from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

app = Flask(__name__)
# Enable JSON Pretty Print
app.json.compact = False

# --- Chrome Configuration ---
def get_driver():
    options = Options()
    options.add_argument("--headless")  # Run invisible
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    # On Render, chrome might be in a different path, this handles local dev
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        print(f"Error initializing Chrome Driver: {e}")
        return None

def extract_lat_long_from_url(url):
    """
    Extracts latitude and longitude from Google Maps URL.
    Example URL: https://www.google.com/maps/place/...!3d23.7508671!4d90.3935266...
    Or: https://www.google.com/maps/@23.7508671,90.3935266,15z...
    """
    # Pattern 1: @lat,lng
    match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
    if match:
        return float(match.group(1)), float(match.group(2))
    
    # Pattern 2: !3dLat!4dLng (seen in /place/ URLs)
    lat_match = re.search(r'!3d(-?\d+\.\d+)', url)
    lng_match = re.search(r'!4d(-?\d+\.\d+)', url)
    
    if lat_match and lng_match:
        return float(lat_match.group(1)), float(lng_match.group(1))
        
    return None, None

def parse_address_string(full_address):
    """
    Attempts to extract Zip, Thana, District, State/Division from a standard Google Maps 
    address string like: "House 32, Road 2, Dhanmondi, Dhaka 1209, Bangladesh"
    """
    details = {
        "full_address": full_address,
        "zip_code": None,
        "thana": None,
        "city": None,
        "district": None,
        "state_division": None,
        "country": None
    }
    
    # Simple regex for BD Zip Code (4 digits)
    zip_match = re.search(r'\b\d{4}\b', full_address)
    if zip_match:
        details['zip_code'] = zip_match.group(0)

    # Split by commas for rough parsing
    parts = [p.strip() for p in full_address.split(',')]
    
    if parts:
        details['country'] = parts[-1]  # Last part is usually country
    
    # Heuristic parsing for Bangladesh addresses
    # Format usually: [Street], [Area/Thana], [City] [Zip], [Country]
    if len(parts) >= 3:
        # Check for City + Zip part (e.g., "Dhaka 1209")
        city_zip_part = parts[-2]
        if any(char.isdigit() for char in city_zip_part):
            # Remove digits/zip to get City/Division name
            # Often "Dhaka 1209" -> City: Dhaka
            cleaned_part = re.sub(r'\d+', '', city_zip_part).strip()
            details['city'] = cleaned_part
            
            # The part before City is often Thana/Area
            details['thana'] = parts[-3]
            
            # If cleaned part looks like a major division, treat as State too
            if "Dhaka" in cleaned_part or "Chittagong" in cleaned_part or "Sylhet" in cleaned_part:
                details['state_division'] = cleaned_part + " Division"
        else:
            # Maybe just City/State
            details['city'] = parts[-2]
            details['thana'] = parts[-3]

    # Try to set District same as City if not found (common in BD)
    if not details['district'] and details['city']:
        details['district'] = details['city'] + " District"

    return details

@app.route('/')
def home():
    return jsonify({
        "message": "Google Maps Verification API (Scraper Edition) is running.",
        "usage": "GET /search?address=... OR POST /enhance {'address': '...'}"
    })

def perform_search(address):
    if not address:
        return jsonify({"status": "error", "message": "Address is required"}), 400

    driver = get_driver()
    if not driver:
        return jsonify({"status": "error", "message": "Could not start browser backend."}), 500

    try:
        # Construct Google Maps Search URL
        search_url = f"https://www.google.com/maps/search/{urllib.parse.quote(address)}"
        print(f"Searching: {search_url}")
        driver.get(search_url)

        # Wait for either result or "not found"
        try:
            # Wait up to 10 seconds for the H1 heading to appear (place name)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "h1"))
            )
        except:
            return jsonify({
                "status": "fake_or_ambiguous",
                "message": "Address not found or ambiguous on Google Maps.",
                "verification": "fake"
            }), 404

        current_url = driver.current_url
        
        # 1. Check if it's a specific place (URL contains /place/)
        if "/place/" in current_url:
            # We found a specific location! Real!
            time.sleep(2) # Allow React to hydrate detailed fields
            
            # Extract Lat/Long from URL
            lat, lng = extract_lat_long_from_url(current_url)

            # Extract H1 (Place Name)
            try:
                place_name = driver.find_element(By.TAG_NAME, "h1").text
            except:
                place_name = address
            
            # Extract Address text 
            full_address_text = ""
            try:
                # Try finding element with aria-label="Address: [text]"
                address_elem = driver.find_element(By.CSS_SELECTOR, "[data-item-id='address']")
                full_address_text = address_elem.get_attribute("aria-label").replace("Address: ", "")
            except:
                # Fallback: grab meta tags? Or use page title?
                page_title = driver.title
                full_address_text = page_title.replace(" - Google Maps", "")

            # Parse details from the string
            parsed = parse_address_string(full_address_text)
            
            return jsonify({
                "status": "success",
                "verification": "real",
                "data": {
                    "place_name": place_name,
                    "full_address": full_address_text,
                    "google_map_url": current_url,
                    "latitude": lat,
                    "longitude": lng,
                    "components": parsed
                }
            })
            
        elif "/search/" in current_url:
             # Check for "Google Maps can't find" text
            page_src = driver.page_source
            if "can't find" in page_src or "Make sure your search is spelled correctly" in page_src:
                 return jsonify({
                    "status": "fake",
                    "verification": "fake",
                    "message": "Google Maps explicitly returned no results."
                }), 404
            else:
                return jsonify({
                    "status": "ambiguous",
                    "verification": "uncertain",
                    "message": "Multiple locations found. Please be more specific."
                })

        return jsonify({"status": "error", "message": "Unknown state"}), 500

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        driver.quit()

@app.route('/enhance', methods=['POST'])
def enhance_address_post():
    data = request.get_json(silent=True) or {}
    address = data.get('address') or request.form.get('address')
    return perform_search(address)

@app.route('/search', methods=['GET'])
def search_address_get():
    # Support /search?address=... and /search?q=... and even /search?text=...
    address = request.args.get('address') or request.args.get('q') or request.args.get('text')
    return perform_search(address)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
