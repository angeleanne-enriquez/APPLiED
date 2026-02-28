# Job Tracker Service

This is the Flask-based **Job Tracker** microservice, refactored to use a
blueprint‑based layout. It provides several endpoints to check health, insert
user/profile information, fetch remote job listings, and inspect the database.

All of the actual route handlers live in the `services/` package; `app.py` is
a thin entrypoint that registers the blueprints and loads configuration.

## Project Layout

```
job-tracker/
├── app.py                # application entry point
├── config.py             # loads .env and exports DATABASE_URL
├── requirements.txt      # python dependencies
├── README.md             # you are reading it
├── services/             # individual feature modules
│   ├── __init__.py       # imports/exports blueprints
│   ├── agent.py          # /agent
│   ├── health.py         # /health, /debug/dburl
│   ├── db.py             # /db and /health/db
│   ├── submit.py         # /submit endpoint
│   ├── jobs.py           # /fetch-jobs and accompanying fetch routine
│   └── profiles.py       # /profiles POST & GET
├── graph/                # agent logic
│   ├── __init__.py       # imports/exports blueprints
│   ├── graph_builder.py  # logic to build the LangGraph graph
│   └── state.py          # State dataclass definition
├── mock/                 # agent logic
│   └── mock_data.py      # mock data for testing endpoints without DB
└── .env                  # (not checked in) environment variables
```

## Getting Started

1. **Checkout the branch** where you want to work (e.g. `mvp-structure`).
   ```powershell
   git checkout mvp-structure
   ```

2. **Create a virtual environment** and activate it:
   ```powershell
   cd C:\APPLiED\job-tracker
   python -m venv venv
   .\venv\Scripts\Activate.ps1 
   ```

3. **Install dependencies**
   ```powershell
   pip install -r requirements.txt
   ```

4. **Configure environment**

   Create a `.env` file next to `app.py` with at least the `DATABASE_URL`:
   ```text
   DATABASE_URL=postgresql://user:pass@host:port/dbname
   ```

   The service uses `python-dotenv` to load this value via `config.py`.

5. **Run the server**
   ```powershell
   python app.py
   ```

   The app will start on **port 5001** by default and log something like:

   ```text
    * Serving Flask app 'app'
    * Debug mode: on
    * Running on http://127.0.0.1:5001
   ```

6. **Test the endpoints (with Mock Data)**
   ```powershell
   curl http://localhost:5001/health
   curl http://localhost:5001/db
   curl http://localhost:5001/fetch-jobs
   # POST a profile:
   curl -X POST http://localhost:5001/profiles -H "Content-Type: application/json" -d '{"email":"a@b.com","first_name":"A","last_name":"B"}'
   # run the agent (matches jobs for a user)
   curl -X POST http://localhost:5001/agent \
        -H "Content-Type: application/json" \
        -d '{"user_id":"123"}'
   ```

   Any request to `/` will return 404; only the routes above are defined.

## Developing and Extending

- Add new features by creating more blueprints under `services/`.
- `app.py` should remain minimal; avoid putting any business logic there.
- Environment-specific settings (e.g. different ports) can be read from
  additional variables in `.env` and used by `app.py`.

## Notes

- The code in the repository root (`app.py`, etc.) previously held all
  endpoints; it has been moved to the `job-tracker/` directory as part of a
  restructure branch (`mvp-structure`).
- The original `job-tracker/` subdirectory from earlier experiments was
  removed and recreated with the current structure.

## License

MIT (see top-level `LICENSE`)
