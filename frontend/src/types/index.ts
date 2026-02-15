export interface Trade {
  id: number;
  order_id: string;
  market_id: string;
  token_id: string;
  side: 'buy' | 'sell';
  price: number;
  size: number;
  filled_size: number;
  status: 'pending' | 'open' | 'filled' | 'partially_filled' | 'cancelled' | 'failed';
  pnl: number;
  outcome?: string;  // YES or NO
  created_at: string;
  updated_at: string;
}

export interface TradeListResponse {
  trades: Trade[];
  total: number;
  page: number;
  page_size: number;
}

export interface Position {
  id: number;
  market_id: string;
  token_id: string;
  outcome: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  current_pnl: number;
  updated_at: string;
}

export interface BotStatus {
  is_running: boolean;
  current_market_id: string | null;
  last_action: string | null;
  total_pnl: number;
  trades_count: number;
  wins: number;
  losses: number;
  updated_at: string;
  time_to_close: number | null;
  paper_trading: boolean;
  paper_balance: number;
  paper_starting_balance: number;
  live_balance: number | null;
}

export interface MarketInfo {
  market_id: string;
  title: string;
  description: string | null;
  end_date: string;
  tokens: MarketToken[];
  time_to_close_minutes: number;
  yes_price: number | null;
  no_price: number | null;
}

export interface MarketToken {
  token_id: string;
  outcome: string;
}

export interface MarketSearchResponse {
  markets: MarketInfo[];
  count: number;
}

export interface PnLSummary {
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  positions: Position[];
}

export interface TradingConfig {
  use_testnet: boolean;
  chain_id: number;
  order_size: number;
  buy_price: number;
  sell_price: number;
  max_loss: number;
  price_target: number;
  time_threshold: number;
}

export interface HealthResponse {
  status: string;
  database: string;
  polymarket_connected: boolean;
  timestamp: string;
}

export interface TradeAnalysisRow {
  timestamp: string;
  market_name: string | null;
  security: string;
  buy_price: number | null;
  sell_price: number | null;
  profit_loss: number;
  cumulative_profit: number;
  cumulative_equity: number;
  is_auto_squared_off: boolean;
}

export interface PerformanceMetrics {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_profit: number;
  avg_loss: number;
  profit_factor: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  avg_trade_duration: number;
  best_trade: number;
  worst_trade: number;
  current_equity: number;
  starting_equity: number;
  equity_curve: number[];
  drawdown_curve: number[];
  timestamps: string[];
}

export interface AnalysisResponse {
  trades: TradeAnalysisRow[];
  metrics: PerformanceMetrics;
}
