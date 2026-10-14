"""Shared configuration, model integration, and local rate limiting."""
import os

# Set before ADK/LiteLLM imports, including the verifier and test collection.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_LOG", "ERROR")
