import { useQuery } from '@tanstack/react-query';
import { Target, Calendar } from 'lucide-react';
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
      <div className="bg-gray-800 rounded-lg p-4 md:p-6 animate-pulse">
        <div className="h-6 bg-gray-700 rounded w-1/3 mb-4"></div>
        <div className="h-16 bg-gray-700 rounded"></div>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded-lg p-4 md:p-6">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3 md:mb-4">
        <Target className="w-4 h-4 md:w-5 md:h-5 text-purple-400" />
        <h2 className="text-base md:text-xl font-semibold text-white">
          Current Market
        </h2>
      </div>

      {/* Market Title */}
      <div className="p-3 md:p-4 bg-gray-700/50 rounded-lg border border-gray-600/50">
        <h3 className="text-sm md:text-base text-white font-medium leading-relaxed">
          {market.title}
        </h3>
        {market.description && (
          <p className="text-xs md:text-sm text-gray-400 mt-2 line-clamp-2">
            {market.description}
          </p>
        )}
        {market.end_date && (
          <div className="flex items-center gap-1.5 mt-2 text-xs text-gray-500">
            <Calendar className="w-3 h-3" />
            <span>Ends: {new Date(market.end_date).toLocaleString()}</span>
          </div>
        )}
      </div>
    </div>
  );
}
