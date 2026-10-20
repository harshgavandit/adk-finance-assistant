"""Vercel FastAPI entrypoint. The existing ADK CLI remains available separately."""
import os
from pathlib import Path
import sys

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_LOG", "ERROR")
sys.path.insert(0, str(Path(__file__).resolve().parent / "ADK_Finance_Assistance_Agent"))

from finance_runtime.web import create_app

app = create_app()
