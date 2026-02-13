import { useQuery } from '@tanstack/react-query';
import { Wallet } from 'lucide-react';
import { getPositions } from '../services/api';

export default function Positions() {
  const { data: positions, isLoading } = useQuery({
    queryKey: ['positions'],
    queryFn: () => getPositions(),
  });

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

  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <h2 className="text-xl font-semibold text-white mb-4 flex items-center gap-2">
        <Wallet className="w-5 h-5" />
        Current Positions
      </h2>

      {!positions || positions.length === 0 ? (
        <div className="text-center py-8 text-gray-400">
          <Wallet className="w-12 h-12 mx-auto mb-2 opacity-50" />
          <p>No open positions</p>
        </div>
      ) : (
        <div className="space-y-3">
          {positions.map((position) => (
            <div
              key={position.id}
              className="p-4 bg-gray-700 rounded-lg border-l-4 border-blue-500"
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
                  <p className="text-sm text-gray-400">P&L</p>
                  <p className="font-semibold">
                    {position.current_pnl >= 0 ? '+' : ''}
                    {position.current_pnl.toFixed(4)}
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 text-sm">
                <div>
                  <p className="text-gray-400">Quantity</p>
                  <p className="text-white font-medium">
                    {position.quantity.toFixed(2)}
                  </p>
                </div>
                <div>
                  <p className="text-gray-400">Avg Price</p>
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
      )}
    </div>
  );
}
