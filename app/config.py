import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
MAX_TENANT_CONNECTIONS = int(os.environ.get("MAX_TENANT_CONNECTIONS", "50"))
PORT = int(os.environ.get("PORT", "8000"))

# Fireworks.ai embedding settings
FIREWORKS_API_KEY = os.environ.get("FIREWORKS_API_KEY", "")
EMBEDDING_MODEL = os.environ.get(
    "EMBEDDING_MODEL", "mixedbread-ai/mxbai-embed-large-v1"
)
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))

# Vector index settings
VECTOR_INDEX_DIR = DATA_DIR / "indexes"
MAX_VECTOR_INDEXES = int(os.environ.get("MAX_VECTOR_INDEXES", "20"))
