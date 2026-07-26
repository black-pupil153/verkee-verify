"""守护进程与看板辅助函数测试"""

from verkeep_verify.monitor.daemon import parse_interval
from verkeep_verify.dashboard import _sparkline, _score_color


def test_parse_interval_units():
    assert parse_interval("90s") == 90
    assert parse_interval("30m") == 1800
    assert parse_interval("6h") == 6 * 3600
    assert parse_interval("1d") == 86400


def test_parse_interval_fallback():
    assert parse_interval("garbage") == 6 * 3600


def test_sparkline_renders():
    spark = _sparkline([70, 75, 80, 85, 90])
    assert len(spark) == 5
    # 单调递增应以最高格结尾
    assert spark[-1] == "█"


def test_sparkline_empty():
    assert _sparkline([]) == ""
    assert _sparkline([None, None]) == ""


def test_score_color_thresholds():
    assert _score_color(90) == "green"
    assert _score_color(75) == "yellow"
    assert _score_color(50) == "red"
    assert _score_color(None) == "dim"
