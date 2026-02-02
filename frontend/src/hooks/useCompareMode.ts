import { useState, useCallback } from 'react';

/**
 * Custom hook for managing stock comparison mode
 * 
 * Features:
 * - Toggle compare mode on/off
 * - Select/deselect stocks for comparison
 * - Enforce max selection limit
 * - Track whether comparison is ready (2+ stocks selected)
 * 
 * @param maxCount - Maximum number of stocks that can be selected (default: 4)
 */
export function useCompareMode(maxCount: number = 4) {
  const [isCompareMode, setIsCompareMode] = useState(false);
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([]);

  /**
   * Toggle compare mode on/off
   * Clears selection when turning off
   */
  const toggleCompareMode = useCallback(() => {
    setIsCompareMode(prev => !prev);
    if (isCompareMode) {
      setSelectedSymbols([]);
    }
  }, [isCompareMode]);

  /**
   * Toggle selection of a stock
   * - If already selected: remove from selection
   * - If not selected and under limit: add to selection
   * - If at limit: do nothing
   * 
   * @param symbol - Stock symbol to toggle
   */
  const toggleStock = useCallback((symbol: string) => {
    setSelectedSymbols(prev => {
      // If already selected, remove it
      if (prev.includes(symbol)) {
        return prev.filter(s => s !== symbol);
      }
      
      // If at max capacity, don't add
      if (prev.length >= maxCount) {
        return prev;
      }
      
      // Add to selection
      return [...prev, symbol];
    });
  }, [maxCount]);

  /**
   * Clear all selected stocks
   */
  const clearSelection = useCallback(() => {
    setSelectedSymbols([]);
  }, []);

  /**
   * Check if a stock is currently selected
   * 
   * @param symbol - Stock symbol to check
   */
  const isSelected = useCallback((symbol: string) => {
    return selectedSymbols.includes(symbol);
  }, [selectedSymbols]);

  /**
   * Check if more stocks can be selected
   */
  const canSelectMore = selectedSymbols.length < maxCount;

  /**
   * Check if we can proceed to comparison (need at least 2 stocks)
   */
  const canCompare = selectedSymbols.length >= 2;

  return {
    // State
    isCompareMode,
    selectedSymbols,
    selectedCount: selectedSymbols.length,
    maxCount,
    
    // Actions
    toggleCompareMode,
    toggleStock,
    clearSelection,
    
    // Helpers
    isSelected,
    canSelectMore,
    canCompare,
  };
}