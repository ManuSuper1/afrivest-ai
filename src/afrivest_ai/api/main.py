import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from afrivest_ai.api.routers import research
from afrivest_ai.config import settings
from afrivest_ai.core.agent import build_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logging.getLogger("afrivest_ai").setLevel(
    logging.DEBUG if settings.debug else logging.INFO
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing AfriVest API and agent bundle")
    try:
        app.state.agent_bundle = build_agent()
    except Exception:
        logger.exception("Agent bundle initialization failed")
        raise
    logger.info("Agent bundle initialized")
    try:
        yield
    finally:
        logger.info("Shutting down AfriVest API")

app = FastAPI(
    title="AfriVest Intelligence API",
    description="Deep Agent Research Engine for Market Entry",
    version="0.1.0",
    lifespan=lifespan,
)

# Standard CORS setup for a premium frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Update for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(research.router)


@app.get("/health")
def health_check():
    return {"status": "healthy"}
