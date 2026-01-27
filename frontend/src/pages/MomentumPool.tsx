import React, { useState } from 'react';
import { useStocks } from '../hooks/useData';
import { StockCard } from '../components/stock';
import { LoadingState, ErrorMessage, Select } from '../components/common';

export function MomentumPool() {
  const [industryFilter, setIndustryFilter] = useState('all');
  const { data: stocks, isLoading, error, refetch } = useStocks();

  // Filter options
  const industryOptions = Array.from(
    new Set((stocks ?? []).map(stock => stock.industry).filter(Boolean))
  ).sort();
  const filterOptions = [
    { value: 'all', label: '全部行业' },
    ...industryOptions.map((industry) => ({ value: industry, label: industry }))
  ];

  // Filter stocks based on industry
  const filteredStocks = stocks?.filter(stock => {
    if (industryFilter === 'all') return true;
    return stock.industry === industryFilter;
  }) ?? [];

  if (isLoading) {
    return <LoadingState message="正在加载动能股数据..." />;
  }

  if (error) {
    return <ErrorMessage error={error} onRetry={refetch} />;
  }

  return (
    <div>
      {/* Page Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <span className="text-xl">⚡</span>
          <h1 className="text-xl font-semibold">行业内动能股详细分析</h1>
          <span className="text-sm text-[var(--text-muted)] ml-2">
            共 {filteredStocks.length} 只股票
          </span>
        </div>
        <div className="flex items-center gap-3">
          <Select
            options={filterOptions}
            value={industryFilter}
            onChange={(e) => setIndustryFilter(e.target.value)}
          />
        </div>
      </div>

      {/* Stock Cards List */}
      <div>
        {filteredStocks.length > 0 ? (
          filteredStocks.map((stock, index) => (
            <StockCard
              key={stock.id}
              stock={stock}
              rank={index + 1}
              onClick={() => console.log('Viewing stock:', stock.symbol)}
            />
          ))
        ) : (
          <div className="text-center py-12 text-[var(--text-muted)]">
            暂无符合条件的股票数据
          </div>
        )}
      </div>
    </div>
  );
}
