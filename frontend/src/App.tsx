import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getBotStatus, getHealth } from './services/api';
import BotControls from './components/BotControls';
import PnLDisplay from './components/PnLDisplay';
import Positions from './components/Positions';
import TradeHistory from './components/TradeHistory';
import MarketInfo from './components/MarketInfo';
import Analysis from './components/Analysis';
import { BarChart3 } from 'lucide-react';

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
  });

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
            <div>
              <h1 className="text-3xl font-bold text-white">
                Polymarket Trading Bot
              </h1>
              <p className="text-gray-400 mt-1">
                Automated trading for Bitcoin 5-minute markets
              </p>
            </div>
            <div className="flex items-center gap-4">
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
