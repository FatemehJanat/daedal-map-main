"""
Test ScienceBase page structure to find download links
"""
import requests
from bs4 import BeautifulSoup

url = "https://www.sciencebase.gov/catalog/item/5bc730dde4b0fc368ebcad8a"

response = requests.get(url, timeout=30)
soup = BeautifulSoup(response.content, 'html.parser')

print("All links containing 'download', 'file', or '.zip':")
print()

for link in soup.find_all('a', href=True):
    href = link['href']
    text = link.get_text(strip=True)

    if 'download' in href.lower() or 'file' in href.lower() or '.zip' in href.lower() or '.mat' in href.lower():
        print(f"Text: {text}")
        print(f"Href: {href}")
        print()

# Also look for specific file references
print("\nSearching for file references in page text:")
page_text = soup.get_text()
if 'pagercat' in page_text.lower():
    lines = page_text.split('\n')
    for i, line in enumerate(lines):
        if 'pagercat' in line.lower() or '.mat' in line.lower() or '.zip' in line.lower():
            print(f"  {line.strip()}")
