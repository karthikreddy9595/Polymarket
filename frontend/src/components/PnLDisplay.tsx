import { useQuery } from '@tanstack/react-query';
import { TrendingUp, TrendingDown, Activity } from 'lucide-react';
import { getPnLSummary } from '../services/api';

export default function PnLDisplay() {
  const { data: pnl, isLoading } = useQuery({
    queryKey: ['pnl'],
    queryFn: getPnLSummary,
  });

  if (isLoading) {
    return (
      <div className="bg-gray-800 rounded-lg p-6 animate-pulse">
        <div className="h-6 bg-gray-700 rounded w-1/3 mb-4"></div>
        <div className="h-16 bg-gray-700 rounded"></div>
      </div>
    );
  }

  const isProfit = (pnl?.total_pnl ?? 0) >= 0;

  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <h2 className="text-xl font-semibold text-white mb-4 flex items-center gap-2">
        <Activity className="w-5 h-5" />
        P&L Summary
      </h2>

      {/* Total P&L */}
      <div
        className={`p-4 rounded-lg mb-4 ${
          isProfit ? 'bg-green-900/30' : 'bg-red-900/30'
        }`}
      >
        <p className="text-sm text-gray-400">Total P&L</p>
        <div className="flex items-center gap-2">
          {isProfit ? (
            <TrendingUp className="w-6 h-6 text-green-400" />
          ) : (
            <TrendingDown className="w-6 h-6 text-red-400" />
          )}
          <span
            className={`text-3xl font-bold ${
              isProfit ? 'text-green-400' : 'text-red-400'
            }`}
          >
            {isProfit ? '+' : ''}
            {pnl?.total_pnl.toFixed(4) ?? '0.0000'}
          </span>
        </div>
      </div>

      {/* Realized / Unrealized */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="p-3 bg-gray-700 rounded-lg">
          <p className="text-xs text-gray-400">Realized</p>
          <p
            className={`text-lg font-semibold ${
              (pnl?.realized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
            }`}
          >
            {(pnl?.realized_pnl ?? 0) >= 0 ? '+' : ''}
            {pnl?.realized_pnl.toFixed(4) ?? '0.0000'}
          </p>
        </div>
        <div className="p-3 bg-gray-700 rounded-lg">
          <p className="text-xs text-gray-400">Unrealized</p>
          <p
            className={`text-lg font-semibold ${
              (pnl?.unrealized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
            }`}
          >
            {(pnl?.unrealized_pnl ?? 0) >= 0 ? '+' : ''}
            {pnl?.unrealized_pnl.toFixed(4) ?? '0.0000'}
          </p>
        </div>
      </div>

      {/* Trade Statistics */}
      <div className="grid grid-cols-3 gap-3">
        <div className="p-3 bg-gray-700 rounded-lg text-center">
          <p className="text-xs text-gray-400">Total Trades</p>
          <p className="text-xl font-semibold text-white">
            {pnl?.total_trades ?? 0}
          </p>
        </div>
        <div className="p-3 bg-gray-700 rounded-lg text-center">
          <p className="text-xs text-gray-400">Win Rate</p>
          <p className="text-xl font-semibold text-blue-400">
            {pnl?.win_rate.toFixed(1) ?? 0}%
          </p>
        </div>
        <div className="p-3 bg-gray-700 rounded-lg text-center">
          <p className="text-xs text-gray-400">W / L</p>
          <p className="text-xl font-semibold">
            <span className="text-green-400">{pnl?.winning_trades ?? 0}</span>
            <span className="text-gray-500"> / </span>
            <span className="text-red-400">{pnl?.losing_trades ?? 0}</span>
          </p>
        </div>
      </div>
    </div>
  );
}
