# County Map - Geographic Data Explorer

Explore geographic data through natural conversation. Ask questions about countries, states, and counties, then visualize the results on an interactive 3D globe.

**Live Demo**: [county-map.up.railway.app](https://county-map.up.railway.app)

---

## What You Can Do

- **Ask questions naturally** - "What GDP data do you have?" or "Show me CO2 emissions for Europe"
- **Get guided suggestions** - The system helps you discover available data and refine your queries
- **Visualize on a map** - Results display on an interactive globe with clickable features
- **Combine data sources** - View GDP alongside health indicators or demographics
- **Filter and compare** - "Top 10 countries by GDP" or "Europe excluding Germany"

---

## Available Data

| Dataset | Coverage | Topics |
|---------|----------|--------|
| OWID CO2 Data | 218 countries | GDP, CO2, energy, population |
| WHO Health Stats | 198 countries | Life expectancy, mortality, immunization |
| IMF Balance of Payments | 195 countries | Trade, investment, financial flows |
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

For technical documentation, see [CONTEXT.md](CONTEXT.md).

| Document | Purpose |
|----------|---------|
| [CONTEXT.md](CONTEXT.md) | System architecture and technical index |
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | Data format and import process |
| [GEOMETRY.md](GEOMETRY.md) | Geography system and location IDs |
| [CHAT.md](CHAT.md) | Chat interface and LLM system |
| [MAPPING.md](MAPPING.md) | Frontend visualization |
| [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md) | Admin tools for data management |
| [ROADMAP.md](ROADMAP.md) | Future features and plans |

---

## License

MIT License

---

*Last Updated: 2025-12-31*
