"""
Test downloading DesInventar data from HDX
"""
import requests
from bs4 import BeautifulSoup

# Try Colombia dataset
url = "https://data.humdata.org/dataset/colombia-disaster-inventory"

print(f"Fetching HDX page: {url}")
print()

try:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    response = requests.get(url, timeout=30, headers=headers)

    print(f"Status: {response.status_code}")
    print()

    soup = BeautifulSoup(response.content, 'html.parser')

    # Find download links
    download_links = []
    for link in soup.find_all('a', href=True):
        href = link['href']
        if '.xls' in href.lower() or '.csv' in href.lower() or 'download' in href.lower():
            text = link.get_text(strip=True)
            if text:  # Only if there's text
                download_links.append({
                    'href': href,
                    'text': text
                })

    print(f"Found {len(download_links)} potential download links:")
    for i, link in enumerate(download_links[:10], 1):  # Show first 10
        print(f"  {i}. {link['text'][:80]}")
        print(f"     {link['href'][:100]}")
        print()

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
