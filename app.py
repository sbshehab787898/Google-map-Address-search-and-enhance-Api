import os
import re
import time
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

def parse_address_string(full_address):
    """
    Attempts to extract Zip, Thana, District from a standard Google Maps 
    address string like: "House 32, Road 2, Dhanmondi, Dhaka 1209, Bangladesh"
    """
    details = {
        "full_address": full_address,
        "zip_code": None,
        "thana": None,
        "city": None,
        "district": None,
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
            # Remove digits to get City name
            city_name = re.sub(r'\d+', '', city_zip_part).strip()
            details['city'] = city_name
            # The part before City is often Thana/Area
            details['thana'] = parts[-3]
        else:
            # Maybe just City
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
        "usage": "Send POST to /enhance with {'address': '...'}. Warning: Slower than API."
    })

@app.route('/enhance', methods=['POST'])
def enhance_address():
    data = request.get_json(silent=True) or {}
    address = data.get('address') or request.form.get('address')
    
    if not address:
        return jsonify({"status": "error", "message": "Address is required"}), 400

    driver = get_driver()
    if not driver:
        return jsonify({"status": "error", "message": "Could not start browser backend."}), 500

    try:
        # Construct Google Maps Search URL
        search_url = f"https://www.google.com/maps/search/{address}"
        print(f"Searching: {search_url}")
        driver.get(search_url)

        # Wait for either result or "not found"
        # We look for a class often associated with the main header or metadata
        try:
            # Wait up to 10 seconds for the H1 heading to appear (place name)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "h1"))
            )
        except:
            # Timeout? Likely "Partial match" listing or Not Found
            # Check if URL redirected to typical "search result list" or stayed put
            # For this simple version, we assume timeout = uncertain/fake
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
            
            # Extract H1 (Place Name)
            try:
                place_name = driver.find_element(By.TAG_NAME, "h1").text
            except:
                place_name = address
            
            # Extract Address text 
            # Google often puts the address in a button with data-item-id="address" 
            # or aria-label containing "Address"
            full_address_text = ""
            try:
                # Try finding element with aria-label="Address: [text]"
                address_elem = driver.find_element(By.CSS_SELECTOR, "[data-item-id='address']")
                full_address_text = address_elem.get_attribute("aria-label").replace("Address: ", "")
            except:
                # Fallback: grab meta tags? Or use page title?
                # Page title format: "Place Name - Address - Google Maps"
                page_title = driver.title
                # Remove " - Google Maps"
                clean_title = page_title.replace(" - Google Maps", "")
                # Often simple logic suffices
                full_address_text = clean_title

            # Parse details from the string
            parsed = parse_address_string(full_address_text)
            
            return jsonify({
                "status": "success",
                "verification": "real",
                "data": {
                    "place_name": place_name,
                    "full_address": full_address_text,
                    "url": current_url,
                    "components": parsed
                }
            })
            
        elif "/search/" in current_url:
             # It stayed on search page.
             # Check for "Google Maps can't find" text
            page_src = driver.page_source
            if "can't find" in page_src or "Make sure your search is spelled correctly" in page_src:
                 return jsonify({
                    "status": "fake",
                    "verification": "fake",
                    "message": "Google Maps explicitly returned no results."
                }), 404
            else:
                # List of results
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
