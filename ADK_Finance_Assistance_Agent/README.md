# Finance Assistant Application

See the [repository README](../README.md) for architecture, setup, configuration,
usage, limitations, verification, troubleshooting and learning references.

The runtime `.env` belongs in this directory. Start from `.env.example` and
supply your own OpenAI API key. Never commit `.env`.

From this directory on Windows:

```powershell
.\run.ps1 -Mode web -Port 8001
.\run.ps1 -Mode check
.\run.ps1 -Mode test
# Optional billable model verification:
.\run.ps1 -Mode live
```

The virtual environment belongs in the repository's parent directory of this
application folder: `../.venv`. Both agents use `LLM_MODEL` (default
`gpt-4o-mini`). Rate limits use local SQLite and need no Redis credentials.
