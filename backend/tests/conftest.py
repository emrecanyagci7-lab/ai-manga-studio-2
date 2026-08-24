import os

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL is missing from env and /app/frontend/.env")
BASE_URL = base_url.rstrip("/")
API = f"{BASE_URL}/api"

# Internal URL is used ONLY as a documented workaround for the long-running
# POST /api/mangas call, which exceeds the public ingress 60s timeout (502).
INTERNAL_API = "http://localhost:8001/api"

CLIENT_ID = "test-client-uuid-1234"


@pytest.fixture(scope="session")
def api_client():
    s = requests.Session()
    return s
