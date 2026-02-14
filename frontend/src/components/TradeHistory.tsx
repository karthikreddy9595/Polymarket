import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { History, ChevronLeft, ChevronRight } from 'lucide-react';
import { getTrades, getBotStatus } from '../services/api';

export default function TradeHistory() {
  const [page, setPage] = useState(1);
  const pageSize = 10;

  // Get current market ID from bot status
  const { data: botStatus } = useQuery({
    queryKey: ['botStatus'],
    queryFn: getBotStatus,
    refetchInterval: 2000,
  });

  const currentMarketId = botStatus?.current_market_id;

  // Show trades from completed markets (exclude current market)
  const { data, isLoading } = useQuery({
    queryKey: ['trades', page, pageSize, currentMarketId],
    queryFn: () => getTrades(page, pageSize, undefined, currentMarketId || undefined),
    refetchInterval: 3000, // Refresh every 3 seconds
  });

  const totalPages = data ? Math.ceil(data.total / pageSize) : 0;

  if (isLoading) {
    return (
      <div className="bg-gray-800 rounded-lg p-6 animate-pulse">
        <div className="h-6 bg-gray-700 rounded w-1/3 mb-4"></div>
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 bg-gray-700 rounded"></div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <h2 className="text-xl font-semibold text-white mb-4 flex items-center gap-2">
        <History className="w-5 h-5" />
        Trade History
      </h2>

      {!data || data.trades.length === 0 ? (
        <div className="text-center py-8 text-gray-400">
          <History className="w-12 h-12 mx-auto mb-2 opacity-50" />
          <p>No trades yet</p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 text-left border-b border-gray-700">
                  <th className="pb-2">Side</th>
                  <th className="pb-2">Price</th>
                  <th className="pb-2">Size</th>
                  <th className="pb-2">Status</th>
                  <th className="pb-2">P&L</th>
                </tr>
              </thead>
              <tbody>
                {data.trades.map((trade) => (
                  <tr
                    key={trade.id}
                    className="border-b border-gray-700/50 hover:bg-gray-700/30"
                  >
                    <td className="py-3">
                      <span
                        className={`px-2 py-1 rounded text-xs font-medium ${
                          trade.side === 'buy'
                            ? 'bg-green-900 text-green-300'
                            : 'bg-red-900 text-red-300'
                        }`}
                      >
                        {trade.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-3 text-white">{trade.price.toFixed(3)}</td>
                    <td className="py-3 text-white">
                      {trade.filled_size.toFixed(2)}/{trade.size.toFixed(2)}
                    </td>
                    <td className="py-3">
                      <span
                        className={`text-xs ${
                          trade.status === 'filled'
                            ? 'text-green-400'
                            : trade.status === 'cancelled' ||
                              trade.status === 'failed'
                            ? 'text-red-400'
                            : 'text-yellow-400'
                        }`}
                      >
                        {trade.status}
                      </span>
                    </td>
                    <td
                      className={`py-3 ${
                        trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}
                    >
                      {trade.pnl >= 0 ? '+' : ''}
                      {trade.pnl.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-700">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="flex items-center gap-1 px-3 py-1 bg-gray-700 rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-600"
              >
                <ChevronLeft className="w-4 h-4" />
                Prev
              </button>
              <span className="text-gray-400 text-sm">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="flex items-center gap-1 px-3 py-1 bg-gray-700 rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-600"
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
