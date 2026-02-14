import { useQuery } from '@tanstack/react-query';
import { Wallet, ArrowUpCircle, ArrowDownCircle } from 'lucide-react';
import { getPositions, getTrades, getBotStatus } from '../services/api';

export default function Positions() {
  // Get current market ID from bot status
  const { data: botStatus } = useQuery({
    queryKey: ['botStatus'],
    queryFn: getBotStatus,
    refetchInterval: 2000,
  });

  const currentMarketId = botStatus?.current_market_id;

  // Get open positions for the current market session
  const { data: positions, isLoading: positionsLoading } = useQuery({
    queryKey: ['positions', currentMarketId],
    queryFn: () => getPositions(currentMarketId || undefined),
    refetchInterval: 2000,
    enabled: true,
  });

  // Get trades for the current market session
  const { data: tradesData, isLoading: tradesLoading } = useQuery({
    queryKey: ['currentSessionTrades', currentMarketId],
    queryFn: () => getTrades(1, 20, currentMarketId || undefined),
    refetchInterval: 2000,
    enabled: !!currentMarketId,
  });

  const isLoading = positionsLoading || tradesLoading;
  const currentTrades = tradesData?.trades || [];

  if (isLoading) {
    return (
      <div className="bg-gray-800 rounded-lg p-6 animate-pulse">
        <div className="h-6 bg-gray-700 rounded w-1/3 mb-4"></div>
        <div className="space-y-3">
          <div className="h-16 bg-gray-700 rounded"></div>
          <div className="h-16 bg-gray-700 rounded"></div>
        </div>
      </div>
    );
  }

  const hasPositions = positions && positions.length > 0;
  const hasTrades = currentTrades.length > 0;

  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <h2 className="text-xl font-semibold text-white mb-4 flex items-center gap-2">
        <Wallet className="w-5 h-5" />
        Current Session
      </h2>

      {/* Open Positions */}
      {hasPositions && (
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-400 mb-2">Open Positions</h3>
          <div className="space-y-2">
            {positions.map((position) => (
              <div
                key={position.id}
                className="p-3 bg-gray-700 rounded-lg border-l-4 border-blue-500"
              >
                <div className="flex justify-between items-start mb-2">
                  <div>
                    <span
                      className={`inline-block px-2 py-1 rounded text-xs font-medium ${
                        position.outcome === 'YES'
                          ? 'bg-green-900 text-green-300'
                          : 'bg-red-900 text-red-300'
                      }`}
                    >
                      {position.outcome}
                    </span>
                  </div>
                  <div
                    className={`text-right ${
                      position.current_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                    }`}
                  >
                    <p className="text-xs text-gray-400">P&L</p>
                    <p className="font-semibold text-sm">
                      {position.current_pnl >= 0 ? '+' : ''}
                      ${position.current_pnl.toFixed(2)}
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <p className="text-gray-400">Qty</p>
                    <p className="text-white font-medium">
                      {position.quantity.toFixed(1)}
                    </p>
                  </div>
                  <div>
                    <p className="text-gray-400">Entry</p>
                    <p className="text-white font-medium">
                      {position.avg_price.toFixed(3)}
                    </p>
                  </div>
                  <div>
                    <p className="text-gray-400">Current</p>
                    <p className="text-white font-medium">
                      {position.current_price.toFixed(3)}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Current Session Trades */}
      <div>
        <h3 className="text-sm font-medium text-gray-400 mb-2">
          Session Trades {currentTrades.length > 0 && `(${currentTrades.length})`}
        </h3>

        {!hasTrades ? (
          <div className="text-center py-4 text-gray-500 text-sm">
            No trades in current session
          </div>
        ) : (
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {currentTrades.map((trade) => (
              <div
                key={trade.id}
                className={`p-2 bg-gray-700/50 rounded flex items-center justify-between border-l-2 ${
                  trade.side === 'buy' ? 'border-green-500' : 'border-red-500'
                }`}
              >
                <div className="flex items-center gap-2">
                  {trade.side === 'buy' ? (
                    <ArrowUpCircle className="w-4 h-4 text-green-400" />
                  ) : (
                    <ArrowDownCircle className="w-4 h-4 text-red-400" />
                  )}
                  <span className="text-white text-sm font-medium">
                    {trade.side.toUpperCase()}
                  </span>
                  <span className="text-gray-400 text-xs">
                    @ {trade.price.toFixed(3)}
                  </span>
                </div>
                <div className="text-right">
                  <span
                    className={`text-xs ${
                      trade.status === 'filled'
                        ? 'text-green-400'
                        : trade.status === 'cancelled' || trade.status === 'failed'
                        ? 'text-red-400'
                        : 'text-yellow-400'
                    }`}
                  >
                    {trade.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {!hasPositions && !hasTrades && (
        <div className="text-center py-6 text-gray-400">
          <Wallet className="w-10 h-10 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No activity in current session</p>
        </div>
      )}
    </div>
  );
}
