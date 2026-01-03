# Future Data Enhancements

## Geographic/Static Data (from country pages)
Extract once from a recent factbook edition (e.g., 2020):
- Geographic coordinates (lat/long for each country)
- Coastline (km)
- Land boundaries (km)
- Elevation extremes (highest/lowest points)
- Area - comparative
- Maritime claims
- Land use percentages (arable, forest, etc.)

These are static/rarely-changing values - only need one year's data.

Source: `factbook-YYYY/geos/XX.html` files (parse all ~250 country pages)

## Additional Numeric Metrics (potential)
- Sex ratio
- Manpower available/fit for military service
- Budget details (revenues, expenditures)
- Pipelines (km by type)
- Population below poverty line

These would require parsing country pages instead of rankorder files.
