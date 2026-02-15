import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getBotStatus, getHealth, getMarketInfo } from './services/api';
import BotControls from './components/BotControls';
import PnLDisplay from './components/PnLDisplay';
import Positions from './components/Positions';
import TradeHistory from './components/TradeHistory';
import MarketInfo from './components/MarketInfo';
import Analysis from './components/Analysis';
import { BarChart3, TrendingUp, TrendingDown } from 'lucide-react';
import { usePriceWebSocket } from './hooks/usePriceWebSocket';

function App() {
  const [showAnalysis, setShowAnalysis] = useState(false);

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 5000,
  });

  const { data: status } = useQuery({
    queryKey: ['botStatus'],
    queryFn: getBotStatus,
    refetchInterval: 2000,
  });

  // Fetch market info for prices
  const { data: market } = useQuery({
    queryKey: ['market', status?.current_market_id],
    queryFn: () => getMarketInfo(status!.current_market_id!),
    enabled: !!status?.current_market_id,
    refetchInterval: 10000,
  });

  // Extract token IDs for WebSocket subscription
  const tokenIds = useMemo(() => {
    if (!market?.tokens) return [];
    return market.tokens.map((t) => t.token_id).filter(Boolean);
  }, [market?.tokens]);

  // Get real-time prices via WebSocket
  const { prices } = usePriceWebSocket({
    tokenIds,
    enabled: !!market && tokenIds.length > 0,
  });

  // Get YES and NO prices
  const yesToken = market?.tokens?.find((t) => t.outcome === 'Yes');
  const noToken = market?.tokens?.find((t) => t.outcome === 'No');
  const yesPrice = yesToken?.token_id
    ? prices[yesToken.token_id] ?? market?.yes_price
    : market?.yes_price;
  const noPrice = noToken?.token_id
    ? prices[noToken.token_id] ?? market?.no_price
    : market?.no_price;

  // Show Analysis page
  if (showAnalysis) {
    return <Analysis onBack={() => setShowAnalysis(false)} />;
  }

  return (
    <div className="min-h-screen bg-gray-900 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <header className="mb-8">
          <div className="flex items-center justify-between">
            {/* Left - Title */}
            <div className="flex-shrink-0">
              <h1 className="text-3xl font-bold text-white">
                Polymarket Trading Bot
              </h1>
              <p className="text-gray-400 mt-1">
                Automated trading for Bitcoin 5-minute markets
              </p>
            </div>

            {/* Center - Live Prices (Always visible) */}
            <div className="flex items-center gap-3">
              {/* UP Price (YES) */}
              <div className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-green-900/60 to-green-800/40 border border-green-600/50 rounded-xl">
                <div className="flex items-center justify-center w-8 h-8 bg-green-500/20 rounded-lg">
                  <TrendingUp className="w-5 h-5 text-green-400" />
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-green-400/80 font-medium">UP</p>
                  <p className="text-xl font-bold text-white font-mono leading-none">
                    {yesPrice?.toFixed(3) ?? '-.---'}
                  </p>
                </div>
                <div className="ml-1 px-2 py-0.5 bg-green-500/20 rounded text-xs text-green-300 font-medium">
                  {yesPrice ? `${(yesPrice * 100).toFixed(0)}%` : '--%'}
                </div>
              </div>

              {/* Divider */}
              <div className="h-10 w-px bg-gray-600"></div>

              {/* DOWN Price (NO) */}
              <div className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-red-900/60 to-red-800/40 border border-red-600/50 rounded-xl">
                <div className="flex items-center justify-center w-8 h-8 bg-red-500/20 rounded-lg">
                  <TrendingDown className="w-5 h-5 text-red-400" />
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-red-400/80 font-medium">DOWN</p>
                  <p className="text-xl font-bold text-white font-mono leading-none">
                    {noPrice?.toFixed(3) ?? '-.---'}
                  </p>
                </div>
                <div className="ml-1 px-2 py-0.5 bg-red-500/20 rounded text-xs text-red-300 font-medium">
                  {noPrice ? `${(noPrice * 100).toFixed(0)}%` : '--%'}
                </div>
              </div>
            </div>

            {/* Right - Actions */}
            <div className="flex items-center gap-4 flex-shrink-0">
              {/* Analysis Button */}
              <button
                onClick={() => setShowAnalysis(true)}
                className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition-colors"
              >
                <BarChart3 size={18} />
                Analysis
              </button>
              <div
                className={`flex items-center gap-2 px-3 py-1 rounded-full text-sm ${
                  health?.polymarket_connected
                    ? 'bg-green-900 text-green-300'
                    : 'bg-red-900 text-red-300'
                }`}
              >
                <span
                  className={`w-2 h-2 rounded-full ${
                    health?.polymarket_connected ? 'bg-green-400' : 'bg-red-400'
                  }`}
                />
                {health?.polymarket_connected ? 'Connected' : 'Disconnected'}
              </div>
            </div>
          </div>
        </header>

        {/* Main Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column - Controls and Status */}
          <div className="space-y-6">
            <BotControls />
            {status?.current_market_id && (
              <MarketInfo marketId={status.current_market_id} />
            )}
          </div>

          {/* Middle Column - P&L and Positions */}
          <div className="space-y-6">
            <PnLDisplay />
            <Positions />
          </div>

          {/* Right Column - Trade History */}
          <div>
            <TradeHistory />
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
