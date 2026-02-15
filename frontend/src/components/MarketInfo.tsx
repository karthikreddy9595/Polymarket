import { useQuery } from '@tanstack/react-query';
import { Clock, Target } from 'lucide-react';
import { getMarketInfo } from '../services/api';

interface MarketInfoProps {
  marketId: string;
}

export default function MarketInfo({ marketId }: MarketInfoProps) {
  const { data: market, isLoading } = useQuery({
    queryKey: ['market', marketId],
    queryFn: () => getMarketInfo(marketId),
    enabled: !!marketId,
    refetchInterval: 10000,
  });

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
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold text-white flex items-center gap-2">
          <Target className="w-5 h-5" />
          Current Market
        </h2>
      </div>

      {/* Time to Close */}
      <div className="p-4 bg-gray-700/50 rounded-lg border border-gray-600/50 mb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-gray-400">
            <Clock className="w-5 h-5" />
            <span className="text-sm font-medium">Time to Close</span>
          </div>
          <p
            className={`text-2xl font-bold font-mono ${
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
      </div>

      {/* Market Title */}
      <div>
        <h3 className="text-white font-medium line-clamp-2">{market.title}</h3>
        {market.description && (
          <p className="text-gray-400 text-sm mt-1 line-clamp-2">
            {market.description}
          </p>
        )}
      </div>
    </div>
  );
}
