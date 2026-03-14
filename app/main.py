from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import DATA_DIR, MAX_TENANT_CONNECTIONS
from app.db.manager import TenantDBManager
from app.db.system import init_system_db
from app.routers.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app.state.system_db = await init_system_db(DATA_DIR)
    app.state.tenant_manager = TenantDBManager(
        data_dir=DATA_DIR,
        max_connections=MAX_TENANT_CONNECTIONS,
    )
    yield
    # Shutdown
    await app.state.tenant_manager.close_all()
    await app.state.system_db.close()


app = FastAPI(
    title="MemoraLabs",
    description="Memory-as-a-Service API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
