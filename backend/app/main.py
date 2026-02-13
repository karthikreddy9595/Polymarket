"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import init_db
from .routes import bot_router, trades_router, positions_router, websocket_router, analysis_router
from .models.schemas import HealthResponse
from .polymarket_client import get_polymarket_client
from .trading_bot import get_trading_bot

settings = get_settings()

# Configure logging - force INFO level for clean output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Force INFO level on root logger
logging.getLogger().setLevel(logging.INFO)

# Suppress noisy library logs - only show warnings/errors
for noisy_logger in [
    "sqlalchemy", "sqlalchemy.engine", "sqlalchemy.pool",
    "aiosqlite", "aiohttp", "urllib3", "httpx", "httpcore",
    "websockets", "uvicorn.access", "uvicorn.error"
]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown."""
    # Startup
    logger.info("Starting Polymarket Trading Bot API...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Initialize Polymarket client
    client = await get_polymarket_client()
    if settings.private_key:
        await client.connect()
        logger.info("Polymarket client connected")
    else:
        logger.warning("No private key configured - running in read-only mode")

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Stop bot if running
    bot = get_trading_bot()
    if bot.is_running:
        await bot.stop()

    # Close Polymarket client
    if client.is_connected:
        await client.close()

    logger.info("Shutdown complete")


app = FastAPI(
    title="Polymarket Trading Bot",
    description="Automated trading bot for Polymarket prediction markets",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(bot_router)
app.include_router(trades_router)
app.include_router(positions_router)
app.include_router(websocket_router)
app.include_router(analysis_router)


@app.get("/", tags=["root"])
async def root():
    """Root endpoint."""
    return {
        "name": "Polymarket Trading Bot",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check endpoint."""
    client = await get_polymarket_client()

    return HealthResponse(
        status="healthy",
        database="connected",
        polymarket_connected=client.is_connected,
        timestamp=datetime.utcnow()
    )


@app.get("/api/config", tags=["config"])
async def get_trading_config():
    """Get current trading configuration (non-sensitive values only)."""
    return {
        "use_testnet": settings.use_testnet,
        "chain_id": settings.chain_id,
        "order_size": settings.order_size,
        "buy_price": settings.buy_price,
        "sell_price": settings.sell_price,
        "max_loss": settings.max_loss,
        "price_target": settings.price_target,
        "time_threshold": settings.time_threshold
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True
    )
