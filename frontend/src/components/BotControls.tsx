import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Play, Square, RefreshCw, FileText, DollarSign } from 'lucide-react';
import { getBotStatus, startBot, stopBot, setPaperTrading } from '../services/api';

export default function BotControls() {
  const queryClient = useQueryClient();
  const [marketId, setMarketId] = useState<string>('');

  const { data: status, isLoading } = useQuery({
    queryKey: ['botStatus'],
    queryFn: getBotStatus,
    refetchInterval: 2000, // Refresh status every 2 seconds
  });

  const startMutation = useMutation({
    mutationFn: (marketId?: string) => startBot(marketId || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['botStatus'] });
    },
  });

  const stopMutation = useMutation({
    mutationFn: stopBot,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['botStatus'] });
    },
  });

  const paperTradingMutation = useMutation({
    mutationFn: (enabled: boolean) => setPaperTrading(enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['botStatus'] });
    },
  });

  const handlePaperTradingToggle = () => {
    if (status && !status.is_running) {
      paperTradingMutation.mutate(!status.paper_trading);
    }
  };

  const handleStart = () => {
    startMutation.mutate(marketId.trim() || undefined);
  };

  const handleStop = () => {
    stopMutation.mutate();
  };

  if (isLoading) {
    return (
      <div className="bg-gray-800 rounded-lg p-6 animate-pulse">
        <div className="h-6 bg-gray-700 rounded w-1/3 mb-4"></div>
        <div className="h-10 bg-gray-700 rounded"></div>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <h2 className="text-xl font-semibold text-white mb-4">Bot Controls</h2>

      {/* Status Indicator */}
      <div className="flex items-center gap-3 mb-4">
        <div
          className={`w-4 h-4 rounded-full ${
            status?.is_running ? 'bg-green-500 animate-pulse' : 'bg-gray-500'
          }`}
        />
        <span className="text-lg">
          {status?.is_running ? 'Running' : 'Stopped'}
        </span>
      </div>

      {/* Paper Trading Toggle */}
      <div className="mb-4 p-3 bg-gray-700 rounded-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-yellow-400" />
            <span className="text-white font-medium">Paper Trading</span>
          </div>
          <button
            onClick={handlePaperTradingToggle}
            disabled={status?.is_running || paperTradingMutation.isPending}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              status?.paper_trading ? 'bg-yellow-500' : 'bg-gray-600'
            } ${status?.is_running ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                status?.paper_trading ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>
        {status?.paper_trading && (
          <div className="mt-3 pt-3 border-t border-gray-600">
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-400">Paper Balance</span>
              <div className="flex items-center gap-1 text-green-400 font-mono">
                <DollarSign className="w-4 h-4" />
                {status.paper_balance.toFixed(2)}
              </div>
            </div>
            <div className="flex items-center justify-between text-sm mt-1">
              <span className="text-gray-400">P&L</span>
              <span className={`font-mono ${
                status.paper_balance - status.paper_starting_balance >= 0
                  ? 'text-green-400'
                  : 'text-red-400'
              }`}>
                {(status.paper_balance - status.paper_starting_balance) >= 0 ? '+' : ''}
                ${(status.paper_balance - status.paper_starting_balance).toFixed(2)}
              </span>
            </div>
          </div>
        )}
        {!status?.paper_trading && (
          <div className="mt-3 pt-3 border-t border-gray-600">
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-400">Live Balance</span>
              <div className="flex items-center gap-1 text-green-400 font-mono">
                <DollarSign className="w-4 h-4" />
                {status?.live_balance !== null && status?.live_balance !== undefined
                  ? status.live_balance.toFixed(2)
                  : 'Loading...'}
              </div>
            </div>
            <p className="text-xs text-red-400 mt-2">
              Live trading enabled - real money will be used
            </p>
          </div>
        )}
      </div>

      {/* Market ID Input */}
      <div className="mb-4">
        <label className="block text-sm text-gray-400 mb-2">
          Market ID (optional - leave empty to auto-discover)
        </label>
        <input
          type="text"
          value={marketId}
          onChange={(e) => setMarketId(e.target.value)}
          disabled={status?.is_running}
          placeholder="Enter market ID or condition ID..."
          className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-50"
        />
      </div>

      {/* Control Buttons */}
      <div className="flex gap-3">
        {!status?.is_running ? (
          <button
            onClick={handleStart}
            disabled={startMutation.isPending}
            className="flex-1 flex items-center justify-center gap-2 bg-green-600 hover:bg-green-700 disabled:bg-green-800 text-white font-medium py-3 px-4 rounded-lg transition-colors"
          >
            {startMutation.isPending ? (
              <RefreshCw className="w-5 h-5 animate-spin" />
            ) : (
              <Play className="w-5 h-5" />
            )}
            Start Bot
          </button>
        ) : (
          <button
            onClick={handleStop}
            disabled={stopMutation.isPending}
            className="flex-1 flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700 disabled:bg-red-800 text-white font-medium py-3 px-4 rounded-lg transition-colors"
          >
            {stopMutation.isPending ? (
              <RefreshCw className="w-5 h-5 animate-spin" />
            ) : (
              <Square className="w-5 h-5" />
            )}
            Stop Bot
          </button>
        )}
      </div>

      {/* Last Action */}
      {status?.last_action && (
        <div className="mt-4 p-3 bg-gray-700 rounded-lg">
          <p className="text-sm text-gray-400">Last Action</p>
          <p className="text-white">{status.last_action}</p>
        </div>
      )}

      {/* Time to Close */}
      {status?.time_to_close !== null && status?.time_to_close !== undefined && (
        <div className="mt-4 p-3 bg-gray-700 rounded-lg">
          <p className="text-sm text-gray-400">Time to Market Close</p>
          <p className="text-2xl font-mono text-yellow-400">
            {status.time_to_close.toFixed(2)} min
          </p>
        </div>
      )}

      {/* Error Messages */}
      {startMutation.isError && (
        <div className="mt-4 p-3 bg-red-900/50 border border-red-700 rounded-lg text-red-300">
          Failed to start bot: {(startMutation.error as Error).message}
        </div>
      )}
      {stopMutation.isError && (
        <div className="mt-4 p-3 bg-red-900/50 border border-red-700 rounded-lg text-red-300">
          Failed to stop bot: {(stopMutation.error as Error).message}
        </div>
      )}
    </div>
  );
}
