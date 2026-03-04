# Automation Command Center

A personal automation platform.

## Structure

```
automation-command-center/
├── automations/
├── integrations/
├── services/
├── dashboards/
├── runbooks/
├── logs/
├── tests/
└── README.md
```

## Setup

1. Copy `.env.example` to `.env` and fill in your credentials (never commit secrets).
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the core service:
   ```bash
   uvicorn services.app:app --reload
   ```

## License

MIT
