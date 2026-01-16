# County Map - Geographic Data Explorer

Explore geographic data through natural conversation. Ask questions about countries, states, and counties, then visualize the results on an interactive 3D globe.

**Live Demo**: [county-map.up.railway.app](https://county-map.up.railway.app)

---

## Features

**Conversational Data Discovery**
- Natural language queries - "What GDP data do you have?" or "Show me CO2 emissions for Europe"
- Guided suggestions help you discover available data and refine your requests
- Order panel lets you review, modify, and confirm data requests before display

**Interactive 3D Globe**
- MapLibre GL JS with globe projection
- Click any country/region for detailed popup with multiple data sources
- Choropleth coloring by selected metric with color legend
- Smooth zooming from world view to county level

**Multi-Source Data Integration**
- Combine data from different sources in single view (GDP + health + demographics)
- Region/continent filtering (Europe, EU, G7, OECD, income levels)
- Exclusion filters ("Europe excluding Germany")
- Smart year selection based on data completeness

**Geographic Coverage**
- 257 countries with standardized boundaries
- 56 regional groupings (WHO regions, trade blocs, income levels)
- Multi-level support: country, state/province, county
- US Census data at county level (3,200+ counties)

---

## Available Data

| Dataset | Coverage | Topics |
|---------|----------|--------|
| OWID CO2 Data | 218 countries | GDP, CO2, energy, population |
| WHO Health Stats | 198 countries | Life expectancy, mortality, immunization |
| IMF Balance of Payments | 195 countries | Trade, investment, financial flows |
| World Factbook | 250 countries | Infrastructure, military, oil/gas, electricity |
| US Census Demographics | 3,200+ counties | Age, sex, race demographics |
| UN SDG Indicators | 200+ countries | 17 Sustainable Development Goals |

---

## Quick Start

1. Clone the repository
2. Add your OpenAI API key to `.env`
3. Install dependencies: `pip install -r requirements.txt`
4. Run: `python app.py`
5. Open http://localhost:7000

---

## Documentation

| Document | Purpose |
|----------|---------|
| [docs/DATA_SCHEMAS.md](docs/DATA_SCHEMAS.md) | Data formats, loc_id specification, parquet schemas |
| [docs/public reference.md](docs/public%20reference.md) | Data source attribution and licensing |
| [examples/](examples/) | Sample converters for adding your own data |

---

## Adding Your Own Data

This project uses a simple schema that makes it easy to add your own datasets:

```python
import pandas as pd

# Your data needs loc_id (location) and year columns
df = pd.DataFrame({
    "loc_id": ["USA-CA", "USA-TX", "USA-NY"],
    "year": [2020, 2020, 2020],
    "my_metric": [100, 200, 150]
})

df.to_parquet("county-map-data/countries/USA/my_source/aggregates.parquet")
```

See [docs/DATA_SCHEMAS.md](docs/DATA_SCHEMAS.md) for the full specification.

---

## License

MIT License

---

*Last Updated: 2026-01-15*
