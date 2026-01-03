"""
Scan all World Factbook editions to build correct field ID mappings.

This script scans raw HTML files from all factbook editions (2000-2020) and extracts:
1. Field IDs from filenames
2. Metric titles from HTML content
3. Row counts (number of countries with data)

Output: field_id_scan_results.json with structure:
{
    "2020": {
        "261": {"title": "Crude oil - production", "row_count": 217, "file_type": "rankorder"},
        ...
    }
}

Structure differences by era:
- 2000-2001: Text-based filenames in fields/ only (airports.html, birth_rate.html)
- 2002: Numeric IDs in fields/ only (2001.html, 2002.html)
- 2003-2017: Both rankorder/ and fields/ directories, 2xxx IDs
- 2018-2020: rankorder files moved INTO fields/ folder, 1xx-3xx IDs
"""

import os
import re
import json
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
import html

RAW_DATA_BASE = r"C:\Users\Bryan\Desktop\county-map-data\Raw data"
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), 'field_id_scan_results.json')

def read_html_file(file_path: str) -> Optional[str]:
    """Read HTML file with encoding fallback."""
    encodings = ['utf-8', 'latin-1', 'windows-1252']
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    return None

def extract_title(html_content: str) -> str:
    """Extract metric title from HTML content."""
    # Try fbTitleRankOrder div first (2015-2017 format)
    fb_title_match = re.search(r'<div[^>]*class=["\']?fbTitleRankOrder["\']?[^>]*>.*?<strong>([^<]+)</strong>', html_content, re.IGNORECASE | re.DOTALL)
    if fb_title_match:
        return html.unescape(fb_title_match.group(1).strip())

    # Try 2011-2014 format: Country Comparison<strong>&nbsp;::&nbsp;TITLE</strong>
    cc_strong_match = re.search(r'Country Comparison<strong>\s*(?:&nbsp;)*\s*::\s*(?:&nbsp;)*\s*([^<]+)</strong>', html_content, re.IGNORECASE)
    if cc_strong_match:
        title = cc_strong_match.group(1).strip()
        title = re.sub(r'\s*[-—]+\s*The World Factbook.*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*[-—]+\s*Central Intelligence Agency.*$', '', title, flags=re.IGNORECASE)
        return html.unescape(title.strip())

    # Try Country Comparison header (2009-2010 and 2018+ format)
    cc_match = re.search(r'Country Comparison\s*::\s*([^<\n]+)', html_content, re.IGNORECASE)
    if cc_match:
        title = cc_match.group(1).strip()
        # Remove suffix with hyphen, en-dash, or em-dash
        title = re.sub(r'\s*[\u2014\u2013\-]+\s*The World Factbook.*$', '', title, flags=re.IGNORECASE)
        return html.unescape(title.strip())

    # Try Rank Order header (2003-2008 format)
    ro_match = re.search(r'Rank Order\s*[-:]+\s*([^<\n]+)', html_content, re.IGNORECASE)
    if ro_match:
        return html.unescape(ro_match.group(1).strip())

    # Try Field Listing header (2002 format)
    fl_match = re.search(r'Field Listing\s*[-:]+\s*([^<\n]+)', html_content, re.IGNORECASE)
    if fl_match:
        return html.unescape(fl_match.group(1).strip())

    # Try <title> tag
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', html_content, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()
        # Clean up common prefixes/suffixes (including em-dash variants)
        title = re.sub(r'^CIA\s*[-:]\s*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'^The World Factbook\s*[-:]*\s*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'^Country Comparison\s*::\s*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'^Rank Order\s*[-:]*\s*', '', title, flags=re.IGNORECASE)
        # Remove suffixes with em-dash, en-dash, or hyphen
        title = re.sub(r'\s*[\u2014\u2013\-]+\s*The World Factbook.*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*[\u2014\u2013\-]+\s*Central Intelligence Agency.*$', '', title, flags=re.IGNORECASE)
        if title and title.lower() not in ['', 'the world factbook', 'central intelligence agency']:
            return html.unescape(title.strip())

    # Try <h2> or <h3> headers
    header_match = re.search(r'<h[23][^>]*>([^<]+)</h[23]>', html_content, re.IGNORECASE)
    if header_match:
        return html.unescape(header_match.group(1).strip())

    return "Unknown"

def count_data_rows(html_content: str, edition_year: int) -> int:
    """Count number of country data rows in the HTML table."""
    # Count rows with country links - most reliable across formats
    # Pattern matches <a href="...geos/XX.html">Country Name</a>
    country_links = re.findall(r'<a[^>]+href="[^"]*geos/[^"]+\.html"[^>]*>', html_content, re.IGNORECASE)
    if country_links:
        return len(country_links)

    # Fallback: count <tr> tags in table body
    tr_matches = re.findall(r'<tr[^>]*>', html_content, re.IGNORECASE)
    # Subtract 1-2 for header rows
    return max(0, len(tr_matches) - 2)

def scan_directory(dir_path: str, edition_year: int, file_type: str) -> Dict[str, dict]:
    """Scan a directory for HTML files and extract metadata."""
    results = {}

    if not os.path.exists(dir_path):
        return results

    for filename in os.listdir(dir_path):
        if not filename.endswith('.html'):
            continue
        if filename == 'index.html':
            continue

        file_path = os.path.join(dir_path, filename)
        content = read_html_file(file_path)
        if not content:
            continue

        # Extract field ID from filename
        # Patterns: 2241rank.html, 2241.html, airports.html, 261rank.html
        if 'rank' in filename.lower():
            field_id = filename.replace('rank.html', '').replace('Rank.html', '')
            actual_file_type = 'rankorder'
        else:
            field_id = filename.replace('.html', '')
            actual_file_type = 'field'

        # Skip print versions
        if 'print' in filename.lower():
            continue

        # Skip variant IDs like 2004a
        if re.search(r'[a-z]$', field_id, re.IGNORECASE) and field_id not in ['area']:
            continue

        title = extract_title(content)
        row_count = count_data_rows(content, edition_year)

        # Only include files with actual data
        if row_count > 0 or actual_file_type == 'rankorder':
            results[field_id] = {
                'title': title,
                'row_count': row_count,
                'file_type': actual_file_type,
                'filename': filename
            }

    return results

def scan_edition(year: int) -> Dict[str, dict]:
    """Scan a single factbook edition."""
    factbook_path = os.path.join(RAW_DATA_BASE, f'factbook-{year}')

    if not os.path.exists(factbook_path):
        print(f"  WARNING: Edition {year} not found at {factbook_path}")
        return {}

    results = {}

    # Check for rankorder/ directory
    rankorder_path = os.path.join(factbook_path, 'rankorder')
    if os.path.exists(rankorder_path):
        rankorder_results = scan_directory(rankorder_path, year, 'rankorder')
        results.update(rankorder_results)
        print(f"  rankorder/: {len(rankorder_results)} files")

    # Check for fields/ directory
    fields_path = os.path.join(factbook_path, 'fields')
    if os.path.exists(fields_path):
        fields_results = scan_directory(fields_path, year, 'field')
        # Merge with rankorder results (rankorder takes precedence for row counts)
        for field_id, data in fields_results.items():
            if field_id not in results:
                results[field_id] = data
            elif data['file_type'] == 'rankorder' and results[field_id]['file_type'] != 'rankorder':
                # If fields/ contains rankorder files (2018-2020 structure)
                results[field_id] = data
        print(f"  fields/: {len(fields_results)} files")

    return results

def normalize_title(title: str) -> str:
    """Normalize metric title for matching."""
    title = title.lower()
    # Remove common variations
    title = re.sub(r'\s*\([^)]*\)\s*', ' ', title)  # Remove parentheticals
    title = re.sub(r'\s*-\s*', ' ', title)  # Replace dashes with spaces
    title = re.sub(r'\s+', ' ', title)  # Collapse whitespace
    return title.strip()

def build_metric_to_field_mapping(scan_results: dict) -> dict:
    """Build mapping from normalized metric names to field IDs by year."""
    metric_mapping = {}

    for year, fields in scan_results.items():
        year_int = int(year)
        for field_id, data in fields.items():
            norm_title = normalize_title(data['title'])
            if norm_title not in metric_mapping:
                metric_mapping[norm_title] = {}
            if year_int not in metric_mapping[norm_title]:
                metric_mapping[norm_title][year_int] = []
            metric_mapping[norm_title][year_int].append({
                'field_id': field_id,
                'row_count': data['row_count'],
                'file_type': data['file_type']
            })

    return metric_mapping

def main():
    print("Scanning World Factbook editions 2000-2020...")
    print("=" * 60)

    all_results = {}

    for year in range(2000, 2021):
        print(f"\nScanning {year}...")
        results = scan_edition(year)
        all_results[str(year)] = results
        print(f"  Total: {len(results)} unique field IDs")

    # Save raw scan results
    print(f"\nSaving results to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    # Print summary
    print("\n" + "=" * 60)
    print("SCAN SUMMARY")
    print("=" * 60)

    for year in range(2000, 2021):
        year_str = str(year)
        if year_str in all_results:
            fields = all_results[year_str]
            rankorder_count = sum(1 for f in fields.values() if f['file_type'] == 'rankorder')
            field_count = sum(1 for f in fields.values() if f['file_type'] == 'field')
            print(f"{year}: {len(fields)} total ({rankorder_count} rankorder, {field_count} field)")

    # Build and show metric mapping
    print("\n" + "=" * 60)
    print("SAMPLE METRIC MAPPINGS")
    print("=" * 60)

    metric_mapping = build_metric_to_field_mapping(all_results)

    # Show some key metrics
    key_metrics = [
        'crude oil production',
        'airports',
        'natural gas production',
        'military expenditures',
        'internet users',
        'gdp purchasing power parity',
        'population',
        'birth rate'
    ]

    for metric in key_metrics:
        print(f"\n{metric}:")
        found = False
        for norm_title, year_data in metric_mapping.items():
            if metric in norm_title:
                for year in sorted(year_data.keys()):
                    for entry in year_data[year]:
                        print(f"  {year}: field_id={entry['field_id']}, rows={entry['row_count']}, type={entry['file_type']}")
                found = True
                break
        if not found:
            print("  NOT FOUND")

    print(f"\nDone! Results saved to {OUTPUT_FILE}")
    return all_results

if __name__ == '__main__':
    main()
