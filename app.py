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
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    # Check for Chrome binary location (Render/Linux specific)
    chrome_bin = os.environ.get("CHROME_BIN") or "/usr/bin/google-chrome" or "/usr/bin/google-chrome-stable"
    if os.path.exists(chrome_bin):
        options.binary_location = chrome_bin
    
    try:
        # Try installing/getting the driver
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver, None
    except Exception as e:
        return None, str(e)

def perform_search(address):
    if not address:
        return jsonify({"status": "error", "message": "Address is required"}), 400

    driver, error_msg = get_driver()
    if not driver:
        return jsonify({
            "status": "error", 
            "message": "Could not start browser backend.", 
            "details": error_msg
        }), 500

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
                # Try finding element with data-item-id="address"
                address_elem = driver.find_element(By.CSS_SELECTOR, "[data-item-id='address']")
                full_address_text = address_elem.get_attribute("aria-label").replace("Address: ", "")
            except:
                # Fallback
                page_title = driver.title
                full_address_text = page_title.replace(" - Google Maps", "")

            # Parse details from the string
            parsed = parse_address_string(full_address_text)
            
            return jsonify({
                "status": "success",
                "verification": "real",
                "type": "single_result",
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
             # Check for "Google Maps can't find" text first
            page_src = driver.page_source
            if "can't find" in page_src or "Make sure your search is spelled correctly" in page_src:
                 return jsonify({
                    "status": "fake",
                    "verification": "fake",
                    "message": "Google Maps explicitly returned no results."
                }), 404
            
            # If we are here, it's likely a LIST of results
            # Scrape the list items
            results = []
            try:
                # Find all anchor tags that link to a specific place
                # These usually have an href containing '/maps/place/' and an aria-label (the name)
                # We wait a moment for the list to load
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/maps/place/']"))
                )
                
                links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/maps/place/']")
                
                for link in links:
                    url = link.get_attribute("href")
                    name = link.get_attribute("aria-label")
                    
                    # Avoid duplicates or empty ones
                    if url and name and "/maps/place/" in url:
                        # Extract lat/long from this URL if possible
                        lat, lng = extract_lat_long_from_url(url)
                        
                        results.append({
                            "place_name": name,
                            "google_map_url": url,
                            "latitude": lat,
                            "longitude": lng
                        })
                        
                # Limit to top 10 results to keep response clean
                results = results[:10]

            except Exception as e:
                print(f"Error scraping list: {e}")
                # If scraping context fails but we are on search page, distinct from "not found"
            
            if results:
                return jsonify({
                    "status": "success",
                    "verification": "ambiguous",
                    "type": "multiple_results",
                    "message": f"Found {len(results)} possible locations.",
                    "data": results
                })
            else:
                return jsonify({
                    "status": "ambiguous",
                    "verification": "uncertain",
                    "message": "Multiple locations found, but could not extract details. Please be more specific."
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
