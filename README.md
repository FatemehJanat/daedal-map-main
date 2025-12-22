# County Map - Geographic Data Explorer

Explore geographic data through natural conversation. Ask questions about countries, states, and counties, then visualize the results on an interactive map.

**Live Demo**: [county-map.up.railway.app](https://county-map.up.railway.app)

---

## What You Can Do

- **Explore data conversationally** - "What GDP data do you have?" / "Tell me about CO2 emissions"
- **Get guided suggestions** - The LLM guides you to refine queries (year, region, top N)
- **Display on map** - Results visualize on an interactive map with clickable features
- **Modify existing data** - "Add population data" / "Show 2020 instead" / "Now show Asia"
- **Query with filters** - "Top 10 countries by GDP" / "Europe excluding Germany"

---

## Quick Start

### Prerequisites
- Python 3.12+
- OpenAI API key

### Installation

```bash
# Clone and enter directory
git clone https://github.com/xyver/county-map.git
cd county-map

# Create .env file
echo OPENAI_API_KEY=your-api-key-here > .env

# Install dependencies
pip install -r requirements.txt

# Start the server
python app.py
```

Open http://localhost:7000 in your browser.

---

## Query Examples

**Simple queries:**
- "Show me all countries"
- "Population of Texas counties"
- "Top 10 countries by CO2 emissions"

**With filters:**
- "Countries with GDP over 1 trillion"
- "Counties in California with population greater than 500,000"

**Regional groupings:**
- "GDP of European Union countries"
- "CO2 emissions for G7 nations"
- "Health stats for ASEAN countries"

---

## Available Data

| Dataset | Coverage | Topics |
|---------|----------|--------|
| OWID CO2 Data | 218 countries | GDP, CO2, energy, population |
| WHO Health Stats | 198 countries | Life expectancy, mortality, immunization |
| IMF Balance of Payments | 195 countries | Trade, investment, financial flows |
| US Census Demographics | 3,200+ counties | Age, sex, race demographics |

See [DATA_CATALOG.md](DATA_CATALOG.md) for complete dataset documentation.

---

## Documentation

| Document | Purpose |
|----------|---------|
| [CONTEXT.md](CONTEXT.md) | System overview and where to find information |
| [DEVELOPER.md](DEVELOPER.md) | Technical documentation for developers |
| [DATA_CATALOG.md](DATA_CATALOG.md) | Complete dataset reference |
| [ROADMAP.md](ROADMAP.md) | Future features and development plans |

---

## Adding New Data

1. Place CSV in `data_pipeline/data_loading/`
2. Run ETL: `python data_pipeline/prepare_data.py`
3. Restart server - new dataset auto-discovered

See [DEVELOPER.md](DEVELOPER.md#adding-new-data) for detailed instructions.

---

## License

MIT License

---

*Last Updated: 2025-12-21*
