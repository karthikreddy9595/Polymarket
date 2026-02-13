# Polymarket Trading Bot

A production-ready automated trading bot for Polymarket prediction markets, featuring a FastAPI backend and React dashboard.

## Features

- **Automated Trading**: Executes trades on Bitcoin 5-minute markets
- **Smart Entry**: Places orders when market is < 3 minutes to close
- **Risk Management**: Max loss (0.3) and price target (0.98) triggers
- **Real-time Dashboard**: Monitor positions, P&L, and trade history
- **Docker Deployment**: Containerized for easy deployment

## Trading Strategy

1. **Market Discovery**: Auto-finds Bitcoin 5-minute markets close to expiry
2. **Entry Timing**: Waits until < 3 minutes to market close
3. **Order Placement**: Places limit buy orders at 0.8 on both YES and NO
4. **Exit Strategy**:
   - After buy fills: Place sell order at 0.5
   - Price target (0.98): Sell positions
   - Max loss (0.3): Square off all positions

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Polymarket API credentials
- Ethereum wallet with funds on Polygon

### Setup

1. Clone and configure:
```bash
cd polymarket_bot
cp .env.example .env
# Edit .env with your credentials
```

2. Build and run:
```bash
docker-compose up --build -d
```

3. Access the dashboard:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000/docs

## Project Structure

```
polymarket_bot/
├── backend/                    # FastAPI Python Backend
│   ├── app/
│   │   ├── main.py            # FastAPI entry point
│   │   ├── config.py          # Configuration
│   │   ├── database.py        # SQLite models
│   │   ├── polymarket_client.py  # Polymarket API wrapper
│   │   ├── trading_bot.py     # Core trading logic
│   │   ├── routes/            # API endpoints
│   │   └── models/            # Pydantic schemas
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                   # React Dashboard
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/        # React components
│   │   ├── services/          # API service
│   │   └── types/             # TypeScript types
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
└── .env.example
```

## API Endpoints

### Bot Control
- `POST /api/bot/start` - Start the trading bot
- `POST /api/bot/stop` - Stop the trading bot
- `GET /api/bot/status` - Get bot status
- `GET /api/bot/markets` - Search for available markets

### Trades
- `GET /api/trades` - Get trade history (paginated)
- `GET /api/trades/{id}` - Get trade by ID

### Positions
- `GET /api/positions` - Get current positions
- `GET /api/positions/pnl` - Get P&L summary

### Health
- `GET /health` - Health check
- `GET /api/config` - Get trading configuration

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `PRIVATE_KEY` | Wallet private key | - |
| `POLYMARKET_API_KEY` | API key | - |
| `POLYMARKET_API_SECRET` | API secret | - |
| `POLYMARKET_API_PASSPHRASE` | API passphrase | - |
| `USE_TESTNET` | Use testnet | `true` |
| `CHAIN_ID` | Chain ID (80002/137) | `80002` |
| `ORDER_SIZE` | Shares per trade | `100` |
| `BUY_PRICE` | Limit buy price | `0.8` |
| `SELL_PRICE` | Sell price after fill | `0.5` |
| `MAX_LOSS` | Square off threshold | `0.3` |
| `PRICE_TARGET` | Sell target price | `0.98` |
| `TIME_THRESHOLD` | Minutes before close | `3` |

## Development

### Backend (with uv)
```bash
cd backend

# Install uv (if not installed)
# Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# Linux/Mac: curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install dependencies
uv venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
uv pip install -e .

# Run the backend
uvicorn app.main:app --reload
```

### Frontend (without Docker)
```bash
cd frontend
npm install
npm run dev
```

## Docker Commands

```bash
# Build and start
docker-compose up --build -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Restart backend only
docker-compose restart backend
```

## Risk Disclaimer

This bot is for educational purposes. Trading on prediction markets involves risk. Never trade with funds you cannot afford to lose. The authors are not responsible for any financial losses.

## License

MIT
