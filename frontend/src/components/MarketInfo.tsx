import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Clock, Target, Wifi, WifiOff } from 'lucide-react';
import { getMarketInfo } from '../services/api';
import { usePriceWebSocket } from '../hooks/usePriceWebSocket';

interface MarketInfoProps {
  marketId: string;
}

export default function MarketInfo({ marketId }: MarketInfoProps) {
  const { data: market, isLoading } = useQuery({
    queryKey: ['market', marketId],
    queryFn: () => getMarketInfo(marketId),
    enabled: !!marketId,
    refetchInterval: 10000, // Refresh market info every 10 seconds (for time to close)
  });

  // Extract token IDs for WebSocket subscription
  const tokenIds = useMemo(() => {
    if (!market?.tokens) return [];
    return market.tokens.map((t) => t.token_id).filter(Boolean);
  }, [market?.tokens]);

  // Get real-time prices via WebSocket
  const { prices, isConnected } = usePriceWebSocket({
    tokenIds,
    enabled: !!market && tokenIds.length > 0,
  });

  // Get YES and NO prices (prefer WebSocket prices, fall back to API)
  const yesToken = market?.tokens?.find((t) => t.outcome === 'Yes');
  const noToken = market?.tokens?.find((t) => t.outcome === 'No');

  const yesPrice = yesToken?.token_id
    ? prices[yesToken.token_id] ?? market?.yes_price
    : market?.yes_price;

  const noPrice = noToken?.token_id
    ? prices[noToken.token_id] ?? market?.no_price
    : market?.no_price;

  if (isLoading || !market) {
    return (
      <div className="bg-gray-800 rounded-lg p-6 animate-pulse">
        <div className="h-6 bg-gray-700 rounded w-1/3 mb-4"></div>
        <div className="h-20 bg-gray-700 rounded"></div>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold text-white flex items-center gap-2">
          <Target className="w-5 h-5" />
          Current Market
        </h2>
        {/* WebSocket connection indicator */}
        <div className="flex items-center gap-1 text-xs">
          {isConnected ? (
            <>
              <Wifi className="w-3 h-3 text-green-400" />
              <span className="text-green-400">Live</span>
            </>
          ) : (
            <>
              <WifiOff className="w-3 h-3 text-yellow-400" />
              <span className="text-yellow-400">Polling</span>
            </>
          )}
        </div>
      </div>

      <div className="mb-4">
        <h3 className="text-white font-medium line-clamp-2">{market.title}</h3>
        {market.description && (
          <p className="text-gray-400 text-sm mt-1 line-clamp-2">
            {market.description}
          </p>
        )}
      </div>

      {/* Time to Close */}
      <div className="p-3 bg-gray-700 rounded-lg mb-4">
        <div className="flex items-center gap-2 text-gray-400 mb-1">
          <Clock className="w-4 h-4" />
          <span className="text-sm">Time to Close</span>
        </div>
        <p
          className={`text-2xl font-mono ${
            market.time_to_close_minutes <= 3
              ? 'text-red-400'
              : market.time_to_close_minutes <= 5
              ? 'text-yellow-400'
              : 'text-green-400'
          }`}
        >
          {market.time_to_close_minutes.toFixed(2)} min
        </p>
      </div>

      {/* Prices */}
      <div className="grid grid-cols-2 gap-3">
        <div className="p-3 bg-green-900/30 rounded-lg">
          <p className="text-sm text-gray-400">YES Price</p>
          <p className="text-xl font-semibold text-green-400 font-mono">
            {yesPrice?.toFixed(3) ?? '-'}
          </p>
        </div>
        <div className="p-3 bg-red-900/30 rounded-lg">
          <p className="text-sm text-gray-400">NO Price</p>
          <p className="text-xl font-semibold text-red-400 font-mono">
            {noPrice?.toFixed(3) ?? '-'}
          </p>
        </div>
      </div>
    </div>
  );
}
