import axios from 'axios';
import type {
  BotStatus,
  Trade,
  TradeListResponse,
  Position,
  PnLSummary,
  MarketInfo,
  MarketSearchResponse,
  TradingConfig,
  HealthResponse,
  AnalysisResponse,
} from '../types';

const API_BASE = import.meta.env.VITE_API_URL || '';

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Bot Control
export const startBot = async (marketId?: string): Promise<BotStatus> => {
  const response = await api.post<BotStatus>('/api/bot/start', {
    market_id: marketId,
  });
  return response.data;
};

export const stopBot = async (): Promise<BotStatus> => {
  const response = await api.post<BotStatus>('/api/bot/stop');
  return response.data;
};

export const getBotStatus = async (): Promise<BotStatus> => {
  const response = await api.get<BotStatus>('/api/bot/status');
  return response.data;
};

export const setPaperTrading = async (enabled: boolean): Promise<BotStatus> => {
  const response = await api.post<BotStatus>('/api/bot/paper-trading', {
    enabled,
  });
  return response.data;
};

// Markets
export const searchMarkets = async (): Promise<MarketSearchResponse> => {
  const response = await api.get<MarketSearchResponse>('/api/bot/markets');
  return response.data;
};

export const getMarketInfo = async (marketId: string): Promise<MarketInfo> => {
  const response = await api.get<MarketInfo>(`/api/bot/market/${marketId}`);
  return response.data;
};

// Trades
export const getTrades = async (
  page = 1,
  pageSize = 20,
  marketId?: string,
  excludeMarketId?: string
): Promise<TradeListResponse> => {
  const params = new URLSearchParams({
    page: page.toString(),
    page_size: pageSize.toString(),
  });
  if (marketId) {
    params.append('market_id', marketId);
  }
  if (excludeMarketId) {
    params.append('exclude_market_id', excludeMarketId);
  }
  const response = await api.get<TradeListResponse>(`/api/trades?${params}`);
  return response.data;
};

export const getTrade = async (tradeId: number): Promise<Trade> => {
  const response = await api.get<Trade>(`/api/trades/${tradeId}`);
  return response.data;
};

// Positions
export const getPositions = async (marketId?: string): Promise<Position[]> => {
  const params = marketId ? `?market_id=${marketId}` : '';
  const response = await api.get<Position[]>(`/api/positions${params}`);
  return response.data;
};

export const getPnLSummary = async (): Promise<PnLSummary> => {
  const response = await api.get<PnLSummary>('/api/positions/pnl');
  return response.data;
};

// Config & Health
export const getTradingConfig = async (): Promise<TradingConfig> => {
  const response = await api.get<TradingConfig>('/api/config');
  return response.data;
};

export const getHealth = async (): Promise<HealthResponse> => {
  const response = await api.get<HealthResponse>('/health');
  return response.data;
};

// Analysis
export interface AnalysisFilters {
  startDate?: string;
  endDate?: string;
  security?: string;
  lastNTrades?: number;
}

export const getAnalysis = async (filters?: AnalysisFilters): Promise<AnalysisResponse> => {
  const params = new URLSearchParams();
  if (filters?.startDate) params.append('start_date', filters.startDate);
  if (filters?.endDate) params.append('end_date', filters.endDate);
  if (filters?.security) params.append('security', filters.security);
  if (filters?.lastNTrades) params.append('last_n_trades', filters.lastNTrades.toString());

  const queryString = params.toString();
  const url = queryString ? `/api/analysis?${queryString}` : '/api/analysis';
  const response = await api.get<AnalysisResponse>(url);
  return response.data;
};

export const exportTrades = async (filters?: AnalysisFilters): Promise<void> => {
  const params = new URLSearchParams();
  if (filters?.startDate) params.append('start_date', filters.startDate);
  if (filters?.endDate) params.append('end_date', filters.endDate);
  params.append('format', 'csv');

  const queryString = params.toString();
  const url = `${API_BASE}/api/analysis/export?${queryString}`;

  // Download file
  const link = document.createElement('a');
  link.href = url;
  link.download = `trades_export.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};

export default api;
