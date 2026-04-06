"""
Relative strength / relative momentum calculator.

Pure calculation module:
- input must be DataFrame(s)
- no external data fetching
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


class MomentumCalculator:
    """Pure relative-momentum calculations on input DataFrames."""

    @classmethod
    def calculate_relative_strength(
        cls,
        sector_df: pd.DataFrame,
        benchmark_df: pd.DataFrame,
    ) -> Optional[pd.DataFrame]:
        """
        Calculate RS and RS changes (5D/20D/63D) from 2 price DataFrames.
        """
        sector = cls._prepare_price_df(sector_df, "sector_price")
        benchmark = cls._prepare_price_df(benchmark_df, "benchmark_price")

        if sector is None or benchmark is None:
            return None

        merged = pd.merge(sector, benchmark, on="date", how="inner")
        if merged.empty:
            return None

        merged = merged.sort_values("date").reset_index(drop=True)

        merged["RS"] = np.where(
            merged["benchmark_price"] != 0,
            merged["sector_price"] / merged["benchmark_price"],
            np.nan,
        )
        merged["RS"] = cls._clean_series(merged["RS"])

        SKIP = 5  # 跳过最近 1 周
        rs = merged["RS"]

        # 20D 和 63D 跳过最近 1 周
        merged["RS_20D_change"] = cls._clean_series(
            (rs.shift(SKIP) - rs.shift(SKIP + 20)) / rs.shift(SKIP + 20)
        )
        merged["RS_63D_change"] = cls._clean_series(
            (rs.shift(SKIP) - rs.shift(SKIP + 63)) / rs.shift(SKIP + 63)
        )

        # 5D 加速项不跳过（捕捉近期加速信号）
        merged["RS_5D_change"] = cls._clean_series(rs.pct_change(5))

        return merged

    @classmethod
    def calculate_rel_mom(cls, rs_df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        Calculate relative momentum:
        RelMom = 0.20*RS_5D + 0.45*RS_20D + 0.35*RS_63D
        """
        if not isinstance(rs_df, pd.DataFrame) or rs_df.empty:
            return None

        result = rs_df.copy()
        for col in ("RS_5D_change", "RS_20D_change", "RS_63D_change"):
            if col not in result.columns:
                result[col] = 0.0
            result[col] = cls._clean_series(result[col])

        result["RelMom"] = (
            result["RS_5D_change"] * 0.20    # 近期加速确认（不跳过最近1周）
            + result["RS_20D_change"] * 0.45  # 主要动量信号（跳过最近1周）
            + result["RS_63D_change"] * 0.35  # 长期趋势锚（跳过最近1周）
        )
        result["RelMom"] = cls._clean_series(result["RelMom"])
        return result

    @classmethod
    def calculate_relative_momentum(
        cls,
        sector_data: pd.DataFrame,
        benchmark_data: pd.DataFrame,
    ) -> Optional[Dict[str, Any]]:
        """
        Return latest RS/RelMom snapshot as dict.
        """
        rs_df = cls.calculate_relative_strength(sector_data, benchmark_data)
        if rs_df is None or rs_df.empty:
            return None

        relmom_df = cls.calculate_rel_mom(rs_df)
        if relmom_df is None or relmom_df.empty:
            return None

        latest = relmom_df.iloc[-1]
        date_value = latest.get("date")
        if hasattr(date_value, "strftime"):
            date_str = date_value.strftime("%Y-%m-%d")
        else:
            date_str = str(date_value)

        return {
            "date": date_str,
            "sector_price": cls._to_float(latest.get("sector_price")),
            "benchmark_price": cls._to_float(latest.get("benchmark_price")),
            "RS": cls._to_float(latest.get("RS")),
            "RS_5D": cls._to_float(latest.get("RS_5D_change")),
            "RS_20D": cls._to_float(latest.get("RS_20D_change")),
            "RS_63D": cls._to_float(latest.get("RS_63D_change")),
            "RelMom": cls._to_float(latest.get("RelMom")),
        }

    @staticmethod
    def _prepare_price_df(df: pd.DataFrame, target_col: str) -> Optional[pd.DataFrame]:
        if not isinstance(df, pd.DataFrame) or df.empty or "date" not in df.columns:
            return None

        value_col = MomentumCalculator._infer_price_column(df)
        if value_col is None:
            return None

        prepared = df[["date", value_col]].copy()
        prepared["date"] = pd.to_datetime(prepared["date"], errors="coerce")
        prepared[target_col] = pd.to_numeric(prepared[value_col], errors="coerce")
        prepared = prepared.drop(columns=[value_col])

        prepared = prepared.dropna(subset=["date"]).sort_values("date")
        if prepared.empty:
            return None

        # NaN/inf tolerance per PR requirement
        prepared[target_col] = (
            prepared[target_col]
            .replace([np.inf, -np.inf], np.nan)
            .ffill()
            .bfill()
            .fillna(0.0)
        )
        return prepared.reset_index(drop=True)

    @staticmethod
    def _infer_price_column(df: pd.DataFrame) -> Optional[str]:
        candidates = ("close", "price", "adj_close", "adjClose")
        for col in candidates:
            if col in df.columns and col != "date":
                return col

        non_date_cols = [col for col in df.columns if col != "date"]
        return non_date_cols[0] if non_date_cols else None

    @staticmethod
    def _clean_series(series: pd.Series) -> pd.Series:
        cleaned = pd.to_numeric(series, errors="coerce")
        cleaned = cleaned.replace([np.inf, -np.inf], np.nan)
        return cleaned.fillna(0.0)

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            if pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

