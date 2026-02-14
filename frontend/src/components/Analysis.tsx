import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getAnalysis, exportTrades, AnalysisFilters } from '../services/api';
import {
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
} from 'recharts';
import { ArrowLeft, TrendingUp, TrendingDown, Activity, Target, Shield, Zap, Download, Filter, X } from 'lucide-react';

interface AnalysisProps {
  onBack: () => void;
}

function Analysis({ onBack }: AnalysisProps) {
  const [filters, setFilters] = useState<AnalysisFilters>({});
  const [showFilters, setShowFilters] = useState(false);
  const [localStartDate, setLocalStartDate] = useState('');
  const [localEndDate, setLocalEndDate] = useState('');
  const [localSecurity, setLocalSecurity] = useState('');

  const { data, isLoading, error } = useQuery({
    queryKey: ['analysis', filters],
    queryFn: () => getAnalysis(filters),
    refetchInterval: 10000,
  });

  const applyFilters = () => {
    setFilters({
      startDate: localStartDate || undefined,
      endDate: localEndDate || undefined,
      security: localSecurity || undefined,
    });
  };

  const clearFilters = () => {
    setLocalStartDate('');
    setLocalEndDate('');
    setLocalSecurity('');
    setFilters({});
  };

  const handleExport = () => {
    exportTrades(filters);
  };

  const hasActiveFilters = filters.startDate || filters.endDate || filters.security;

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-900 p-6 flex items-center justify-center">
        <div className="text-gray-400">Loading analysis...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-900 p-6 flex items-center justify-center">
        <div className="text-red-400">Error loading analysis</div>
      </div>
    );
  }

  const metrics = data?.metrics;
  const trades = data?.trades || [];

  // Prepare data for charts - show ALL datapoints
  const equityData = metrics?.equity_curve.map((value, index) => ({
    name: metrics.timestamps[index] || `${index}`,
    equity: value,
    drawdown: metrics.drawdown_curve[index] || 0,
  })) || [];

  const winLossData = [
    { name: 'Wins', value: metrics?.winning_trades || 0, color: '#10B981' },
    { name: 'Losses', value: metrics?.losing_trades || 0, color: '#EF4444' },
  ];

  // Show ALL trades in the P&L chart
  const pnlData = trades.map((trade, index) => ({
    name: `#${index + 1}`,
    pnl: trade.profit_loss,
    cumulative: trade.cumulative_profit,
  }));

  return (
    <div className="min-h-screen bg-gray-900 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <header className="mb-8">
          <button
            onClick={onBack}
            className="flex items-center gap-2 text-gray-400 hover:text-white mb-4 transition-colors"
          >
            <ArrowLeft size={20} />
            Back to Dashboard
          </button>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-white">Trading Analysis</h1>
              <p className="text-gray-400 mt-1">
                Performance metrics and trade history
                {trades.length > 0 && ` (${trades.length} trades)`}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setShowFilters(!showFilters)}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                  hasActiveFilters
                    ? 'bg-purple-600 hover:bg-purple-700 text-white'
                    : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                }`}
              >
                <Filter size={18} />
                Filters
                {hasActiveFilters && (
                  <span className="bg-white text-purple-600 text-xs px-1.5 py-0.5 rounded-full">
                    Active
                  </span>
                )}
              </button>
              <button
                onClick={handleExport}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
              >
                <Download size={18} />
                Export CSV
              </button>
            </div>
          </div>
        </header>

        {/* Filter Panel */}
        {showFilters && (
          <div className="bg-gray-800 rounded-lg p-4 mb-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-white">Filters</h3>
              {hasActiveFilters && (
                <button
                  onClick={clearFilters}
                  className="flex items-center gap-1 text-sm text-gray-400 hover:text-white"
                >
                  <X size={16} />
                  Clear all
                </button>
              )}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Start Date</label>
                <input
                  type="date"
                  value={localStartDate}
                  onChange={(e) => setLocalStartDate(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-purple-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">End Date</label>
                <input
                  type="date"
                  value={localEndDate}
                  onChange={(e) => setLocalEndDate(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-purple-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Security</label>
                <select
                  value={localSecurity}
                  onChange={(e) => setLocalSecurity(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-purple-500"
                >
                  <option value="">All</option>
                  <option value="Up">Up</option>
                  <option value="Down">Down</option>
                </select>
              </div>
              <div className="flex items-end">
                <button
                  onClick={applyFilters}
                  className="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition-colors"
                >
                  Apply Filters
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Key Metrics Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
          <MetricCard
            title="Win Rate"
            value={`${metrics?.win_rate || 0}%`}
            icon={<Target className="text-green-400" size={20} />}
            color="green"
          />
          <MetricCard
            title="Total P&L"
            value={`$${metrics?.total_pnl?.toFixed(2) || '0.00'}`}
            icon={metrics?.total_pnl && metrics.total_pnl >= 0 ?
              <TrendingUp className="text-green-400" size={20} /> :
              <TrendingDown className="text-red-400" size={20} />}
            color={metrics?.total_pnl && metrics.total_pnl >= 0 ? 'green' : 'red'}
          />
          <MetricCard
            title="Sharpe Ratio"
            value={metrics?.sharpe_ratio?.toFixed(2) || '0.00'}
            icon={<Activity className="text-blue-400" size={20} />}
            color="blue"
          />
          <MetricCard
            title="Max Drawdown"
            value={`${metrics?.max_drawdown_pct?.toFixed(1) || 0}%`}
            icon={<Shield className="text-yellow-400" size={20} />}
            color="yellow"
          />
          <MetricCard
            title="Profit Factor"
            value={metrics?.profit_factor?.toFixed(2) || '0.00'}
            icon={<Zap className="text-purple-400" size={20} />}
            color="purple"
          />
          <MetricCard
            title="Total Trades"
            value={metrics?.total_trades?.toString() || '0'}
            icon={<Activity className="text-cyan-400" size={20} />}
            color="cyan"
          />
        </div>

        {/* Charts Row 1 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Equity Curve */}
          <div className="bg-gray-800 rounded-lg p-4">
            <h3 className="text-lg font-semibold text-white mb-4">
              Equity Curve ({equityData.length} points)
            </h3>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={equityData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis
                  dataKey="name"
                  stroke="#9CA3AF"
                  fontSize={10}
                  interval={Math.max(0, Math.floor(equityData.length / 10) - 1)}
                  angle={-45}
                  textAnchor="end"
                  height={60}
                />
                <YAxis stroke="#9CA3AF" fontSize={12} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1F2937', border: 'none' }}
                  labelStyle={{ color: '#9CA3AF' }}
                />
                <Area
                  type="monotone"
                  dataKey="equity"
                  stroke="#10B981"
                  fill="#10B98133"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Drawdown Chart */}
          <div className="bg-gray-800 rounded-lg p-4">
            <h3 className="text-lg font-semibold text-white mb-4">Drawdown</h3>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={equityData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis
                  dataKey="name"
                  stroke="#9CA3AF"
                  fontSize={10}
                  interval={Math.max(0, Math.floor(equityData.length / 10) - 1)}
                  angle={-45}
                  textAnchor="end"
                  height={60}
                />
                <YAxis stroke="#9CA3AF" fontSize={12} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1F2937', border: 'none' }}
                  labelStyle={{ color: '#9CA3AF' }}
                />
                <Area
                  type="monotone"
                  dataKey="drawdown"
                  stroke="#EF4444"
                  fill="#EF444433"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Charts Row 2 */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
          {/* Win/Loss Pie Chart */}
          <div className="bg-gray-800 rounded-lg p-4">
            <h3 className="text-lg font-semibold text-white mb-4">Win/Loss Distribution</h3>
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={winLossData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="value"
                  label={({ name, value }) => `${name}: ${value}`}
                >
                  {winLossData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ backgroundColor: '#1F2937', border: 'none' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* P&L per Trade - Shows ALL trades */}
          <div className="bg-gray-800 rounded-lg p-4 lg:col-span-2">
            <h3 className="text-lg font-semibold text-white mb-4">
              P&L per Trade ({pnlData.length} trades)
            </h3>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={pnlData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis
                  dataKey="name"
                  stroke="#9CA3AF"
                  fontSize={10}
                  interval={Math.max(0, Math.floor(pnlData.length / 20) - 1)}
                />
                <YAxis stroke="#9CA3AF" fontSize={12} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1F2937', border: 'none' }}
                  labelStyle={{ color: '#9CA3AF' }}
                />
                <Bar
                  dataKey="pnl"
                  fill="#10B981"
                  radius={[2, 2, 0, 0]}
                >
                  {pnlData.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={entry.pnl >= 0 ? '#10B981' : '#EF4444'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Cumulative P&L Chart */}
        <div className="bg-gray-800 rounded-lg p-4 mb-6">
          <h3 className="text-lg font-semibold text-white mb-4">Cumulative P&L</h3>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={pnlData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="name"
                stroke="#9CA3AF"
                fontSize={10}
                interval={Math.max(0, Math.floor(pnlData.length / 15) - 1)}
              />
              <YAxis stroke="#9CA3AF" fontSize={12} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1F2937', border: 'none' }}
                labelStyle={{ color: '#9CA3AF' }}
              />
              <Area
                type="monotone"
                dataKey="cumulative"
                stroke="#8B5CF6"
                fill="#8B5CF633"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Detailed Metrics */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <div className="bg-gray-800 rounded-lg p-4">
            <h3 className="text-lg font-semibold text-white mb-4">Performance Metrics</h3>
            <div className="grid grid-cols-2 gap-4">
              <MetricRow label="Winning Trades" value={metrics?.winning_trades || 0} />
              <MetricRow label="Losing Trades" value={metrics?.losing_trades || 0} />
              <MetricRow label="Avg Profit" value={`$${metrics?.avg_profit?.toFixed(4) || '0.00'}`} />
              <MetricRow label="Avg Loss" value={`$${metrics?.avg_loss?.toFixed(4) || '0.00'}`} />
              <MetricRow label="Best Trade" value={`$${metrics?.best_trade?.toFixed(4) || '0.00'}`} />
              <MetricRow label="Worst Trade" value={`$${metrics?.worst_trade?.toFixed(4) || '0.00'}`} />
              <MetricRow label="Sortino Ratio" value={metrics?.sortino_ratio?.toFixed(2) || '0.00'} />
              <MetricRow label="Current Equity" value={`$${metrics?.current_equity?.toFixed(2) || '0.00'}`} />
            </div>
          </div>

          <div className="bg-gray-800 rounded-lg p-4">
            <h3 className="text-lg font-semibold text-white mb-4">Risk Metrics</h3>
            <div className="grid grid-cols-2 gap-4">
              <MetricRow label="Max Drawdown $" value={`$${metrics?.max_drawdown?.toFixed(2) || '0.00'}`} />
              <MetricRow label="Max Drawdown %" value={`${metrics?.max_drawdown_pct?.toFixed(2) || '0'}%`} />
              <MetricRow label="Starting Equity" value={`$${metrics?.starting_equity?.toFixed(2) || '0.00'}`} />
              <MetricRow label="Profit Factor" value={metrics?.profit_factor?.toFixed(2) || '0.00'} />
              <MetricRow label="Sharpe Ratio" value={metrics?.sharpe_ratio?.toFixed(2) || '0.00'} />
              <MetricRow label="Sortino Ratio" value={metrics?.sortino_ratio?.toFixed(2) || '0.00'} />
              <MetricRow label="Win Rate" value={`${metrics?.win_rate?.toFixed(1) || '0'}%`} />
              <MetricRow label="Avg Duration" value={`${metrics?.avg_trade_duration?.toFixed(1) || '0'} min`} />
            </div>
          </div>
        </div>

        {/* Trade History Table */}
        <div className="bg-gray-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-white">
              Trade History ({trades.length} trades)
            </h3>
          </div>
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-800">
                <tr className="text-gray-400 border-b border-gray-700">
                  <th className="text-left py-3 px-4">#</th>
                  <th className="text-left py-3 px-4">Timestamp</th>
                  <th className="text-left py-3 px-4">Security</th>
                  <th className="text-right py-3 px-4">Buy Price</th>
                  <th className="text-right py-3 px-4">Sell Price</th>
                  <th className="text-right py-3 px-4">P&L</th>
                  <th className="text-right py-3 px-4">Cumulative P&L</th>
                  <th className="text-right py-3 px-4">Equity</th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="text-center py-8 text-gray-500">
                      No trades yet
                    </td>
                  </tr>
                ) : (
                  trades.map((trade, index) => (
                    <tr
                      key={index}
                      className="border-b border-gray-700 hover:bg-gray-750"
                    >
                      <td className="py-3 px-4 text-gray-500">{index + 1}</td>
                      <td className="py-3 px-4 text-gray-300">{trade.timestamp}</td>
                      <td className="py-3 px-4">
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          trade.security === 'Up' ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'
                        }`}>
                          {trade.security}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right text-gray-300">
                        {trade.buy_price?.toFixed(4) || '-'}
                      </td>
                      <td className="py-3 px-4 text-right text-gray-300">
                        {trade.sell_price?.toFixed(4) || '-'}
                      </td>
                      <td className={`py-3 px-4 text-right font-medium ${
                        trade.profit_loss >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {trade.profit_loss >= 0 ? '+' : ''}{trade.profit_loss.toFixed(4)}
                      </td>
                      <td className={`py-3 px-4 text-right ${
                        trade.cumulative_profit >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {trade.cumulative_profit >= 0 ? '+' : ''}{trade.cumulative_profit.toFixed(4)}
                      </td>
                      <td className="py-3 px-4 text-right text-white font-medium">
                        ${trade.cumulative_equity.toFixed(2)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ title, value, icon, color }: {
  title: string;
  value: string;
  icon: React.ReactNode;
  color: string;
}) {
  const colorClasses: Record<string, string> = {
    green: 'bg-green-900/20 border-green-800',
    red: 'bg-red-900/20 border-red-800',
    blue: 'bg-blue-900/20 border-blue-800',
    yellow: 'bg-yellow-900/20 border-yellow-800',
    purple: 'bg-purple-900/20 border-purple-800',
    cyan: 'bg-cyan-900/20 border-cyan-800',
  };

  return (
    <div className={`rounded-lg p-4 border ${colorClasses[color] || colorClasses.blue}`}>
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <span className="text-xs text-gray-400">{title}</span>
      </div>
      <div className="text-xl font-bold text-white">{value}</div>
    </div>
  );
}

function MetricRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex justify-between items-center py-2 border-b border-gray-700">
      <span className="text-gray-400 text-sm">{label}</span>
      <span className="text-white font-medium">{value}</span>
    </div>
  );
}

export default Analysis;
