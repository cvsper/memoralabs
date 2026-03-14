import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
MAX_TENANT_CONNECTIONS = int(os.environ.get("MAX_TENANT_CONNECTIONS", "50"))
PORT = int(os.environ.get("PORT", "8000"))
