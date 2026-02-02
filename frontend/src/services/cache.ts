// ============================================================================
// API Cache Utility for Momentum Analysis Frontend
// ============================================================================

/**
 * 简单的内存缓存实现
 * 
 * 特性:
 * - TTL (Time To Live) 支持
 * - LRU 淘汰策略
 * - 自动清理过期缓存
 * - 支持泛型类型
 */

// ============================================================================
// Types
// ============================================================================

interface CacheEntry<T> {
  data: T;
  timestamp: number;
  ttl: number;
}

interface CacheOptions {
  /** 缓存过期时间（毫秒），默认 5 分钟 */
  ttl?: number;
  /** 最大缓存条目数，默认 100 */
  maxSize?: number;
}

// ============================================================================
// Cache Class
// ============================================================================

export class ApiCache {
  private cache: Map<string, CacheEntry<unknown>> = new Map();
  private accessOrder: string[] = [];
  private maxSize: number;
  private defaultTtl: number;

  constructor(options: CacheOptions = {}) {
    this.maxSize = options.maxSize ?? 100;
    this.defaultTtl = options.ttl ?? 5 * 60 * 1000; // 5 分钟

    // 定期清理过期缓存
    if (typeof window !== 'undefined') {
      setInterval(() => this.cleanup(), 60 * 1000); // 每分钟清理一次
    }
  }

  /**
   * 获取缓存数据
   */
  get<T>(key: string): T | null {
    const entry = this.cache.get(key) as CacheEntry<T> | undefined;

    if (!entry) {
      return null;
    }

    // 检查是否过期
    if (this.isExpired(entry)) {
      this.cache.delete(key);
      this.removeFromAccessOrder(key);
      return null;
    }

    // 更新访问顺序（LRU）
    this.updateAccessOrder(key);

    return entry.data;
  }

  /**
   * 设置缓存数据
   */
  set<T>(key: string, data: T, ttl?: number): void {
    // 如果缓存已满，淘汰最久未访问的条目
    if (this.cache.size >= this.maxSize && !this.cache.has(key)) {
      this.evictLRU();
    }

    const entry: CacheEntry<T> = {
      data,
      timestamp: Date.now(),
      ttl: ttl ?? this.defaultTtl,
    };

    this.cache.set(key, entry);
    this.updateAccessOrder(key);
  }

  /**
   * 检查缓存是否存在且有效
   */
  has(key: string): boolean {
    const entry = this.cache.get(key);
    if (!entry) return false;
    if (this.isExpired(entry)) {
      this.cache.delete(key);
      this.removeFromAccessOrder(key);
      return false;
    }
    return true;
  }

  /**
   * 删除指定缓存
   */
  delete(key: string): boolean {
    this.removeFromAccessOrder(key);
    return this.cache.delete(key);
  }

  /**
   * 删除匹配前缀的所有缓存
   */
  deleteByPrefix(prefix: string): number {
    let count = 0;
    for (const key of this.cache.keys()) {
      if (key.startsWith(prefix)) {
        this.delete(key);
        count++;
      }
    }
    return count;
  }

  /**
   * 清空所有缓存
   */
  clear(): void {
    this.cache.clear();
    this.accessOrder = [];
  }

  /**
   * 获取缓存大小
   */
  get size(): number {
    return this.cache.size;
  }

  /**
   * 获取缓存统计信息
   */
  getStats(): { size: number; maxSize: number; keys: string[] } {
    return {
      size: this.cache.size,
      maxSize: this.maxSize,
      keys: Array.from(this.cache.keys()),
    };
  }

  // 私有方法

  private isExpired(entry: CacheEntry<unknown>): boolean {
    return Date.now() - entry.timestamp > entry.ttl;
  }

  private updateAccessOrder(key: string): void {
    this.removeFromAccessOrder(key);
    this.accessOrder.push(key);
  }

  private removeFromAccessOrder(key: string): void {
    const index = this.accessOrder.indexOf(key);
    if (index > -1) {
      this.accessOrder.splice(index, 1);
    }
  }

  private evictLRU(): void {
    const keyToEvict = this.accessOrder.shift();
    if (keyToEvict) {
      this.cache.delete(keyToEvict);
    }
  }

  private cleanup(): void {
    for (const [key, entry] of this.cache.entries()) {
      if (this.isExpired(entry)) {
        this.delete(key);
      }
    }
  }
}

// ============================================================================
// Global Cache Instance
// ============================================================================

export const apiCache = new ApiCache({
  ttl: 5 * 60 * 1000,  // 5 分钟
  maxSize: 200,
});

// ============================================================================
// Cache Key Generators
// ============================================================================

export const CacheKeys = {
  stockList: (params?: Record<string, unknown>) => 
    `stocks:list:${params ? JSON.stringify(params) : 'all'}`,
  
  stockDetail: (symbol: string) => 
    `stocks:detail:${symbol.toUpperCase()}`,
  
  stocksByHeat: (heatType: string, params?: Record<string, unknown>) => 
    `stocks:heat:${heatType}:${params ? JSON.stringify(params) : 'default'}`,
  
  stockCompare: (symbols: string[]) => 
    `stocks:compare:${symbols.sort().join(',')}`,
  
  sectors: () => 'sectors:list',
  
  sectorStocks: (sector: string) => 
    `sectors:stocks:${sector}`,
  
  sectorSummary: (sector: string) => 
    `sectors:summary:${sector}`,
  
  allSectorSummaries: () => 'sectors:summaries:all',
  
  heatDistribution: () => 'stocks:heat:distribution',
  
  search: (query: string, limit: number) => 
    `stocks:search:${query}:${limit}`,
};

// ============================================================================
// Cache TTL Constants (毫秒)
// ============================================================================

export const CacheTTL = {
  /** 股票列表 - 5 分钟 */
  STOCK_LIST: 5 * 60 * 1000,
  
  /** 股票详情 - 3 分钟 */
  STOCK_DETAIL: 3 * 60 * 1000,
  
  /** 热度数据 - 5 分钟 */
  HEAT_DATA: 5 * 60 * 1000,
  
  /** 对比数据 - 2 分钟 */
  COMPARE_DATA: 2 * 60 * 1000,
  
  /** 板块数据 - 10 分钟 */
  SECTOR_DATA: 10 * 60 * 1000,
  
  /** 搜索结果 - 1 分钟 */
  SEARCH: 1 * 60 * 1000,
  
  /** 热度分布 - 5 分钟 */
  HEAT_DISTRIBUTION: 5 * 60 * 1000,
};

// ============================================================================
// Cached Fetch Wrapper
// ============================================================================

interface CachedFetchOptions {
  /** 缓存键 */
  cacheKey: string;
  /** 缓存 TTL */
  ttl?: number;
  /** 是否强制刷新（忽略缓存） */
  forceRefresh?: boolean;
}

/**
 * 带缓存的 fetch 包装器
 */
export async function cachedFetch<T>(
  fetchFn: () => Promise<T>,
  options: CachedFetchOptions
): Promise<T> {
  const { cacheKey, ttl, forceRefresh = false } = options;

  // 检查缓存
  if (!forceRefresh) {
    const cached = apiCache.get<T>(cacheKey);
    if (cached !== null) {
      return cached;
    }
  }

  // 执行请求
  const data = await fetchFn();

  // 存入缓存
  apiCache.set(cacheKey, data, ttl);

  return data;
}

// ============================================================================
// Cache Invalidation Helpers
// ============================================================================

/**
 * 使股票相关缓存失效
 */
export function invalidateStockCache(symbol?: string): void {
  if (symbol) {
    // 使特定股票的缓存失效
    apiCache.delete(CacheKeys.stockDetail(symbol));
  }
  // 使列表缓存失效
  apiCache.deleteByPrefix('stocks:list:');
  apiCache.deleteByPrefix('stocks:heat:');
  apiCache.delete(CacheKeys.heatDistribution());
}

/**
 * 使板块相关缓存失效
 */
export function invalidateSectorCache(sector?: string): void {
  if (sector) {
    apiCache.delete(CacheKeys.sectorStocks(sector));
    apiCache.delete(CacheKeys.sectorSummary(sector));
  }
  apiCache.delete(CacheKeys.sectors());
  apiCache.delete(CacheKeys.allSectorSummaries());
}

/**
 * 使所有缓存失效
 */
export function invalidateAllCache(): void {
  apiCache.clear();
}

// ============================================================================
// Export
// ============================================================================

export default apiCache;
