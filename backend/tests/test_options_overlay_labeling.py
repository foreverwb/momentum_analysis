from app.services.broker.futu.iv_calculator import IVTermResult
from app.services.calculators.etf_score import ETFScoreCalculator


def test_options_overlay_labels_event_heat_and_penalizes_score() -> None:
    calc = ETFScoreCalculator(ibkr=None)
    iv_data = IVTermResult(
        iv30=36.0,
        iv60=31.0,
        iv90=26.0,  # slope = iv30 - iv90 > 0, 事件风险特征
        oi_bucket_8_30=1200,
        oi_bucket_31_90=900,
        net_delta5d_8_30=-40,
        net_delta5d_31_90=-30,
        net_delta3d_8_30=-20,
        net_delta3d_31_90=-15,
    )
    result = calc.calculate_options_confirm_score(
        symbol="EVENT",
        mc_data={
            "heat_score": 86,
            "risk_score": 92,
            "confidence_penalty": 35,
        },
        iv_data=iv_data,
    )

    assert result["data"]["overlay_label"] == "EVENT_HEAT"
    assert result["data"]["position_suggestion"] == "reduce_exposure"
    assert result["score"] < 70


def test_options_overlay_labels_trend_heat_and_adds_bonus() -> None:
    calc = ETFScoreCalculator(ibkr=None)
    iv_data = IVTermResult(
        iv30=22.0,
        iv60=24.0,
        iv90=26.0,  # slope <= 0, 更偏趋势延续结构
        oi_bucket_8_30=1000,
        oi_bucket_31_90=1400,
        net_delta5d_8_30=160,
        net_delta5d_31_90=220,
        net_delta3d_8_30=80,
        net_delta3d_31_90=110,
    )
    result = calc.calculate_options_confirm_score(
        symbol="TREND",
        mc_data={
            "heat_score": 82,
            "risk_score": 65,
            "confidence_penalty": 20,
        },
        iv_data=iv_data,
    )

    assert result["data"]["overlay_label"] == "TREND_HEAT"
    assert result["data"]["position_suggestion"] == "trend_confirmed"
    assert result["score"] >= 70

