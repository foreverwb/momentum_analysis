import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.time_utils import beijing_today, get_beijing_cutoff_boundary


def test_beijing_today_uses_utc_input_as_source_timezone() -> None:
    assert beijing_today(datetime(2026, 3, 15, 20, 30, 0)) == datetime(2026, 3, 16, 4, 30, 0).date()


def test_get_beijing_cutoff_boundary_before_cutoff_rolls_back_one_day() -> None:
    boundary = get_beijing_cutoff_boundary(datetime(2026, 3, 15, 23, 30, 0))

    assert boundary["boundary_date"].isoformat() == "2026-03-15"
    assert boundary["sync_date"] == "2026-03-15"
    assert boundary["boundary_utc"] == datetime(2026, 3, 15, 0, 0, 0)


def test_get_beijing_cutoff_boundary_after_cutoff_stays_same_day() -> None:
    boundary = get_beijing_cutoff_boundary(datetime(2026, 3, 16, 1, 30, 0))

    assert boundary["boundary_date"].isoformat() == "2026-03-16"
    assert boundary["sync_date"] == "2026-03-16"
    assert boundary["boundary_utc"] == datetime(2026, 3, 16, 0, 0, 0)
