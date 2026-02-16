import { useState, useMemo } from 'react';
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
  ReferenceLine,
} from 'recharts';
import { ArrowLeft, TrendingUp, TrendingDown, Activity, Target, Shield, Zap, Download, Filter, X, ChevronUp, ChevronDown, Search } from 'lucide-react';

interface AnalysisProps {
  onBack: () => void;
}

type SortField = 'timestamp' | 'profit_loss' | 'cumulative_profit' | 'security';
type SortOrder = 'asc' | 'desc';

function Analysis({ onBack }: AnalysisProps) {
  const [filters, setFilters] = useState<AnalysisFilters>({});
  const [showFilters, setShowFilters] = useState(false);
  const [localStartDate, setLocalStartDate] = useState('');
  const [localEndDate, setLocalEndDate] = useState('');
  const [localSecurity, setLocalSecurity] = useState('');

  // Table sorting and filtering state
  const [tableSortField, setTableSortField] = useState<SortField>('timestamp');
  const [tableSortOrder, setTableSortOrder] = useState<SortOrder>('desc');
  const [tableSearchQuery, setTableSearchQuery] = useState('');
  const [tableSecurityFilter, setTableSecurityFilter] = useState<string>('');
  const [tablePnlFilter, setTablePnlFilter] = useState<string>('');

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

  // Extract data from query result
  const metrics = data?.metrics;
  const trades = data?.trades || [];

  // Get starting equity from metrics
  const startingEquity = metrics?.starting_equity ?? 1000;

  // First, calculate cumulative values in chronological order (oldest to newest)
  const tradesWithCumulatives = useMemo(() => {
    if (!trades || trades.length === 0) return [];

    // Sort by timestamp ascending (oldest first) to calculate cumulative values correctly
    const chronologicalTrades = [...trades].sort((a, b) => {
      const timeA = a.timestamp ? new Date(a.timestamp).getTime() : 0;
      const timeB = b.timestamp ? new Date(b.timestamp).getTime() : 0;
      return timeA - timeB;
    });

    // Calculate cumulative values in chronological order
    let cumulativeProfit = 0;
    let cumulativeEquity = startingEquity;

    return chronologicalTrades.map(trade => {
      cumulativeProfit += trade.profit_loss ?? 0;
      cumulativeEquity += trade.profit_loss ?? 0;
      return {
        ...trade,
        cumulative_profit: Math.round(cumulativeProfit * 10000) / 10000,
        cumulative_equity: Math.round(cumulativeEquity * 100) / 100,
      };
    });
  }, [trades, startingEquity]);

  // Sorted and filtered trades for table display - must be before any conditional returns
  const sortedAndFilteredTrades = useMemo(() => {
    if (!tradesWithCumulatives || tradesWithCumulatives.length === 0) return [];

    let filtered = [...tradesWithCumulatives];

    // Apply search filter (market name)
    if (tableSearchQuery) {
      const query = tableSearchQuery.toLowerCase();
      filtered = filtered.filter(trade =>
        trade.market_name?.toLowerCase()?.includes(query)
      );
    }

    // Apply security filter
    if (tableSecurityFilter) {
      filtered = filtered.filter(trade => trade.security === tableSecurityFilter);
    }

    // Apply P&L filter
    if (tablePnlFilter === 'profit') {
      filtered = filtered.filter(trade => (trade.profit_loss ?? 0) > 0);
    } else if (tablePnlFilter === 'loss') {
      filtered = filtered.filter(trade => (trade.profit_loss ?? 0) < 0);
    }

    // Apply sorting for display
    filtered.sort((a, b) => {
      let comparison = 0;
      switch (tableSortField) {
        case 'timestamp':
          const timeA = a.timestamp ? new Date(a.timestamp).getTime() : 0;
          const timeB = b.timestamp ? new Date(b.timestamp).getTime() : 0;
          comparison = timeA - timeB;
          break;
        case 'profit_loss':
          comparison = (a.profit_loss ?? 0) - (b.profit_loss ?? 0);
          break;
        case 'cumulative_profit':
          comparison = (a.cumulative_profit ?? 0) - (b.cumulative_profit ?? 0);
          break;
        case 'security':
          comparison = (a.security ?? '').localeCompare(b.security ?? '');
          break;
      }
      return tableSortOrder === 'asc' ? comparison : -comparison;
    });

    return filtered;
  }, [tradesWithCumulatives, tableSearchQuery, tableSecurityFilter, tablePnlFilter, tableSortField, tableSortOrder]);

  // Show recent 20 trades in the P&L chart (sorted by timestamp ascending for chronological view)
  const pnlData = useMemo(() => {
    if (!trades || trades.length === 0) return [];

    const sortedTrades = [...trades].sort((a, b) => {
      const timeA = a.timestamp ? new Date(a.timestamp).getTime() : 0;
      const timeB = b.timestamp ? new Date(b.timestamp).getTime() : 0;
      return timeA - timeB;
    });
    // Take only the last 20 trades for the bar chart
    const recentTrades = sortedTrades.slice(-20);
    const startIndex = sortedTrades.length - recentTrades.length;
    return recentTrades.map((trade, index) => ({
      name: `#${startIndex + index + 1}`,
      pnl: trade.profit_loss ?? 0,
      cumulative: trade.cumulative_profit ?? 0,
      timestamp: trade.timestamp ?? '',
    }));
  }, [trades]);

  // Prepare data for charts
  const equityData = useMemo(() => {
    if (!metrics?.equity_curve) return [];
    return metrics.equity_curve.map((value, index) => ({
      name: metrics?.timestamps?.[index] || `${index}`,
      equity: value,
      drawdown: metrics?.drawdown_curve?.[index] || 0,
    }));
  }, [metrics]);

  const winLossData = useMemo(() => [
    { name: 'Wins', value: metrics?.winning_trades || 0, color: '#10B981' },
    { name: 'Losses', value: metrics?.losing_trades || 0, color: '#EF4444' },
  ], [metrics?.winning_trades, metrics?.losing_trades]);

  // Handle sort column click
  const handleSort = (field: SortField) => {
    if (tableSortField === field) {
      setTableSortOrder(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setTableSortField(field);
      setTableSortOrder('desc');
    }
  };

  // Sort indicator component
  const SortIndicator = ({ field }: { field: SortField }) => {
    if (tableSortField !== field) return null;
    return tableSortOrder === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />;
  };

  // Early returns for loading/error states - AFTER all hooks
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

  return (
    <div className="min-h-screen bg-gray-900 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <header className="mb-6 md:mb-8">
          <button
            onClick={onBack}
            className="flex items-center gap-2 text-gray-400 hover:text-white mb-3 md:mb-4 transition-colors text-sm md:text-base"
          >
            <ArrowLeft size={18} className="md:w-5 md:h-5" />
            <span className="hidden sm:inline">Back to Dashboard</span>
            <span className="sm:hidden">Back</span>
          </button>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4">
            <div>
              <h1 className="text-xl md:text-3xl font-bold text-white">Trading Analysis</h1>
              <p className="text-gray-400 text-xs md:text-base mt-0.5 md:mt-1">
                <span className="hidden sm:inline">Performance metrics and trade history</span>
                <span className="sm:hidden">Performance metrics</span>
                {trades.length > 0 && ` (${trades.length} trades)`}
              </p>
            </div>
            <div className="flex items-center gap-2 md:gap-3">
              <button
                onClick={() => setShowFilters(!showFilters)}
                className={`flex items-center gap-1.5 md:gap-2 px-3 md:px-4 py-1.5 md:py-2 rounded-lg transition-colors text-sm md:text-base ${
                  hasActiveFilters
                    ? 'bg-purple-600 hover:bg-purple-700 text-white'
                    : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                }`}
              >
                <Filter size={16} className="md:w-[18px] md:h-[18px]" />
                <span className="hidden sm:inline">Filters</span>
                {hasActiveFilters && (
                  <span className="bg-white text-purple-600 text-xs px-1.5 py-0.5 rounded-full">
                    Active
                  </span>
                )}
              </button>
              <button
                onClick={handleExport}
                className="flex items-center gap-1.5 md:gap-2 px-3 md:px-4 py-1.5 md:py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors text-sm md:text-base"
              >
                <Download size={16} className="md:w-[18px] md:h-[18px]" />
                <span className="hidden sm:inline">Export CSV</span>
                <span className="sm:hidden">Export</span>
              </button>
            </div>
          </div>
        </header>

        {/* Filter Panel */}
        {showFilters && (
          <div className="bg-gray-800 rounded-lg p-3 md:p-4 mb-4 md:mb-6">
            <div className="flex items-center justify-between mb-3 md:mb-4">
              <h3 className="text-base md:text-lg font-semibold text-white">Filters</h3>
              {hasActiveFilters && (
                <button
                  onClick={clearFilters}
                  className="flex items-center gap-1 text-xs md:text-sm text-gray-400 hover:text-white"
                >
                  <X size={14} className="md:w-4 md:h-4" />
                  Clear all
                </button>
              )}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 md:gap-4">
              <div>
                <label className="block text-xs md:text-sm text-gray-400 mb-1">Start Date</label>
                <input
                  type="date"
                  value={localStartDate}
                  onChange={(e) => setLocalStartDate(e.target.value)}
                  className="w-full px-2 md:px-3 py-1.5 md:py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500"
                />
              </div>
              <div>
                <label className="block text-xs md:text-sm text-gray-400 mb-1">End Date</label>
                <input
                  type="date"
                  value={localEndDate}
                  onChange={(e) => setLocalEndDate(e.target.value)}
                  className="w-full px-2 md:px-3 py-1.5 md:py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500"
                />
              </div>
              <div>
                <label className="block text-xs md:text-sm text-gray-400 mb-1">Security</label>
                <select
                  value={localSecurity}
                  onChange={(e) => setLocalSecurity(e.target.value)}
                  className="w-full px-2 md:px-3 py-1.5 md:py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500"
                >
                  <option value="">All</option>
                  <option value="Up">Up</option>
                  <option value="Down">Down</option>
                </select>
              </div>
              <div className="flex items-end">
                <button
                  onClick={applyFilters}
                  className="w-full px-3 md:px-4 py-1.5 md:py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition-colors text-sm md:text-base"
                >
                  Apply
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Key Metrics Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2 md:gap-4 mb-4 md:mb-8">
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
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6 mb-4 md:mb-6">
          {/* Equity Curve */}
          <div className="bg-gray-800 rounded-lg p-3 md:p-4">
            <h3 className="text-base md:text-lg font-semibold text-white mb-3 md:mb-4">
              Equity Curve ({equityData.length} pts)
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
          <div className="bg-gray-800 rounded-lg p-3 md:p-4">
            <h3 className="text-base md:text-lg font-semibold text-white mb-3 md:mb-4">Drawdown</h3>
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
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-6 mb-4 md:mb-6">
          {/* Win/Loss Pie Chart */}
          <div className="bg-gray-800 rounded-lg p-3 md:p-4">
            <h3 className="text-base md:text-lg font-semibold text-white mb-3 md:mb-4">Win/Loss</h3>
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

          {/* P&L per Trade - Shows recent 20 trades */}
          <div className="bg-gray-800 rounded-lg p-3 md:p-4 lg:col-span-2">
            <h3 className="text-base md:text-lg font-semibold text-white mb-3 md:mb-4">
              P&L per Trade {trades.length > 20 ? `(${pnlData.length}/${trades.length})` : `(${pnlData.length})`}
            </h3>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={pnlData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis
                  dataKey="name"
                  stroke="#9CA3AF"
                  fontSize={10}
                  interval={pnlData.length <= 20 ? 0 : Math.floor(pnlData.length / 15)}
                  tick={{ fill: '#9CA3AF' }}
                />
                <YAxis
                  stroke="#9CA3AF"
                  fontSize={12}
                  tickFormatter={(value) => value.toFixed(2)}
                  domain={['auto', 'auto']}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1F2937', border: 'none', borderRadius: '8px' }}
                  labelStyle={{ color: '#9CA3AF' }}
                  formatter={(value) => [`$${Number(value).toFixed(4)}`, 'P&L']}
                />
                <ReferenceLine y={0} stroke="#6B7280" strokeDasharray="3 3" />
                <Bar
                  dataKey="pnl"
                  radius={[2, 2, 0, 0]}
                  maxBarSize={50}
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
        <div className="bg-gray-800 rounded-lg p-3 md:p-4 mb-4 md:mb-6">
          <h3 className="text-base md:text-lg font-semibold text-white mb-3 md:mb-4">Cumulative P&L</h3>
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
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6 mb-4 md:mb-6">
          <div className="bg-gray-800 rounded-lg p-3 md:p-4">
            <h3 className="text-base md:text-lg font-semibold text-white mb-3 md:mb-4">Performance Metrics</h3>
            <div className="grid grid-cols-2 gap-2 md:gap-4">
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

          <div className="bg-gray-800 rounded-lg p-3 md:p-4">
            <h3 className="text-base md:text-lg font-semibold text-white mb-3 md:mb-4">Risk Metrics</h3>
            <div className="grid grid-cols-2 gap-2 md:gap-4">
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
        <div className="bg-gray-800 rounded-lg p-3 md:p-4">
          <div className="flex items-center justify-between mb-3 md:mb-4">
            <h3 className="text-base md:text-lg font-semibold text-white">
              Trade History ({sortedAndFilteredTrades.length}/{trades.length})
            </h3>
          </div>

          {/* Table Filters */}
          <div className="flex flex-wrap items-center gap-2 md:gap-3 mb-3 md:mb-4 p-2 md:p-3 bg-gray-700/50 rounded-lg">
            {/* Search */}
            <div className="relative flex-1 min-w-[120px] md:min-w-[200px]">
              <Search className="absolute left-2 md:left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-3.5 h-3.5 md:w-4 md:h-4" />
              <input
                type="text"
                placeholder="Search..."
                value={tableSearchQuery}
                onChange={(e) => setTableSearchQuery(e.target.value)}
                className="w-full pl-7 md:pl-9 pr-2 md:pr-3 py-1.5 md:py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-xs md:text-sm focus:outline-none focus:border-purple-500"
              />
            </div>

            {/* Security Filter */}
            <select
              value={tableSecurityFilter}
              onChange={(e) => setTableSecurityFilter(e.target.value)}
              className="px-2 md:px-3 py-1.5 md:py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-xs md:text-sm focus:outline-none focus:border-purple-500"
            >
              <option value="">All</option>
              <option value="Up">Up</option>
              <option value="Down">Down</option>
            </select>

            {/* P&L Filter */}
            <select
              value={tablePnlFilter}
              onChange={(e) => setTablePnlFilter(e.target.value)}
              className="px-2 md:px-3 py-1.5 md:py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-xs md:text-sm focus:outline-none focus:border-purple-500"
            >
              <option value="">P&L</option>
              <option value="profit">Profit</option>
              <option value="loss">Loss</option>
            </select>

            {/* Clear Filters */}
            {(tableSearchQuery || tableSecurityFilter || tablePnlFilter) && (
              <button
                onClick={() => {
                  setTableSearchQuery('');
                  setTableSecurityFilter('');
                  setTablePnlFilter('');
                }}
                className="flex items-center gap-1 px-2 md:px-3 py-1.5 md:py-2 text-gray-400 hover:text-white text-xs md:text-sm"
              >
                <X size={14} className="md:w-4 md:h-4" />
                <span className="hidden sm:inline">Clear</span>
              </button>
            )}
          </div>

          <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-800">
                <tr className="text-gray-400 border-b border-gray-700">
                  <th className="text-left py-3 px-4">#</th>
                  <th
                    className="text-left py-3 px-4 cursor-pointer hover:text-white select-none"
                    onClick={() => handleSort('timestamp')}
                  >
                    <span className="flex items-center gap-1">
                      Timestamp
                      <SortIndicator field="timestamp" />
                    </span>
                  </th>
                  <th className="text-left py-3 px-4 min-w-[300px]">Market</th>
                  <th
                    className="text-left py-3 px-4 cursor-pointer hover:text-white select-none"
                    onClick={() => handleSort('security')}
                  >
                    <span className="flex items-center gap-1">
                      Security
                      <SortIndicator field="security" />
                    </span>
                  </th>
                  <th className="text-right py-3 px-4">Buy Price</th>
                  <th className="text-center py-3 px-4">Buy Status</th>
                  <th className="text-right py-3 px-4">Sell Price</th>
                  <th className="text-center py-3 px-4">Sell Status</th>
                  <th
                    className="text-right py-3 px-4 cursor-pointer hover:text-white select-none"
                    onClick={() => handleSort('profit_loss')}
                  >
                    <span className="flex items-center justify-end gap-1">
                      P&L
                      <SortIndicator field="profit_loss" />
                    </span>
                  </th>
                  <th
                    className="text-right py-3 px-4 cursor-pointer hover:text-white select-none"
                    onClick={() => handleSort('cumulative_profit')}
                  >
                    <span className="flex items-center justify-end gap-1">
                      Cumulative P&L
                      <SortIndicator field="cumulative_profit" />
                    </span>
                  </th>
                  <th className="text-right py-3 px-4">Equity</th>
                </tr>
              </thead>
              <tbody>
                {sortedAndFilteredTrades.length === 0 ? (
                  <tr>
                    <td colSpan={11} className="text-center py-8 text-gray-500">
                      {trades.length === 0 ? 'No trades yet' : 'No trades match filters'}
                    </td>
                  </tr>
                ) : (
                  sortedAndFilteredTrades.map((trade, index) => (
                    <tr
                      key={index}
                      className={`border-b border-gray-700 hover:bg-gray-700/50 ${
                        trade.is_auto_squared_off ? 'bg-yellow-900/20' : ''
                      }`}
                    >
                      <td className="py-3 px-4 text-gray-500">{index + 1}</td>
                      <td className="py-3 px-4 text-gray-300">{trade.timestamp}</td>
                      <td className="py-3 px-4 text-gray-300 min-w-[300px]">
                        {trade.market_name ? (
                          <span className="flex items-center gap-2">
                            <span className="whitespace-normal break-words">{trade.market_name}</span>
                            {trade.is_auto_squared_off && (
                              <span className="text-xs bg-yellow-700 text-yellow-200 px-1 rounded flex-shrink-0">Auto</span>
                            )}
                          </span>
                        ) : (
                          <span className="text-gray-500">Unknown</span>
                        )}
                      </td>
                      <td className="py-3 px-4">
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          trade.security === 'Up' ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'
                        }`}>
                          {trade.security || '-'}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right text-gray-300">
                        {trade.buy_price?.toFixed(4) || '-'}
                      </td>
                      <td className="py-3 px-4 text-center">
                        <span className={`text-xs px-2 py-1 rounded ${
                          trade.buy_status === 'filled' ? 'bg-green-900 text-green-300' :
                          trade.buy_status === 'cancelled' || trade.buy_status === 'failed' ? 'bg-red-900 text-red-300' :
                          'bg-yellow-900 text-yellow-300'
                        }`}>
                          {trade.buy_status || '-'}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right text-gray-300">
                        {trade.sell_price?.toFixed(4) || '-'}
                        {trade.is_auto_squared_off && (
                          <span className="text-xs text-yellow-400 ml-1">(0.995)</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-center">
                        <span className={`text-xs px-2 py-1 rounded ${
                          trade.sell_status === 'filled' ? 'bg-green-900 text-green-300' :
                          trade.sell_status === 'cancelled' || trade.sell_status === 'failed' ? 'bg-red-900 text-red-300' :
                          trade.sell_status === 'auto_squared' ? 'bg-yellow-900 text-yellow-300' :
                          'bg-yellow-900 text-yellow-300'
                        }`}>
                          {trade.sell_status || '-'}
                        </span>
                      </td>
                      <td className={`py-3 px-4 text-right font-medium ${
                        (trade.profit_loss ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {(trade.profit_loss ?? 0) >= 0 ? '+' : ''}{(trade.profit_loss ?? 0).toFixed(4)}
                      </td>
                      <td className={`py-3 px-4 text-right ${
                        (trade.cumulative_profit ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {(trade.cumulative_profit ?? 0) >= 0 ? '+' : ''}{(trade.cumulative_profit ?? 0).toFixed(4)}
                      </td>
                      <td className="py-3 px-4 text-right text-white font-medium">
                        ${(trade.cumulative_equity ?? 0).toFixed(2)}
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
    <div className={`rounded-lg p-2 md:p-4 border ${colorClasses[color] || colorClasses.blue}`}>
      <div className="flex items-center gap-1 md:gap-2 mb-1 md:mb-2">
        {icon}
        <span className="text-[10px] md:text-xs text-gray-400 truncate">{title}</span>
      </div>
      <div className="text-base md:text-xl font-bold text-white truncate">{value}</div>
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
