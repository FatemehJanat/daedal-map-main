"""
Test script to check DesInventar download mechanism
"""
import requests
from bs4 import BeautifulSoup

country_code = "col"
url = f"https://www.desinventar.net/DesInventar/download_base.jsp?countrycode={country_code}"

print(f"Fetching: {url}")
print()

try:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    response = requests.get(url, timeout=30, headers=headers)

    print(f"Status: {response.status_code}")
    print(f"Content-Type: {response.headers.get('Content-Type')}")
    print(f"Content length: {len(response.content)} bytes")
    print()

    # Parse HTML to find download link
    soup = BeautifulSoup(response.content, 'html.parser')

    # Look for links to .zip or .xml files
    download_links = []
    for link in soup.find_all('a', href=True):
        href = link['href']
        if '.zip' in href.lower() or '.xml' in href.lower() or 'download' in href.lower():
            download_links.append({
                'href': href,
                'text': link.get_text(strip=True)
            })

    print(f"Found {len(download_links)} potential download links:")
    for i, link in enumerate(download_links, 1):
        print(f"  {i}. {link['text']}")
        print(f"     URL: {link['href']}")

    # Check for any file size mentions
    text = soup.get_text()
    if 'Mb' in text or 'MB' in text or 'kb' in text.lower():
        print("\nFile size mentions found in page:")
        lines = text.split('\n')
        for line in lines:
            if 'Mb' in line or 'MB' in line or 'kb' in line.lower():
                print(f"  {line.strip()}")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
