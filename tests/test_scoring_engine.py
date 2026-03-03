"""
智能评分引擎单元测试
"""

import math

import pytest

from models.schemas import Frequency, PerformanceRecord, ScoreResult
from agents.scoring_engine import ScoringEngine


@pytest.fixture
def engine():
    """创建使用默认配置的评分引擎实例。"""
    return ScoringEngine()


# ---------------------------------------------------------------------------
# calculate_score 测试
# ---------------------------------------------------------------------------

def test_calculate_score_zero(engine):
    """所有指标为 0 时，分数应为 0。"""
    record = PerformanceRecord(content_id=1, likes=0, comments=0, shares=0, views=0)
    score = engine.calculate_score(record)
    assert score == 0.0


def test_calculate_score_high_engagement(engine):
    """高互动数据，分数应 >= 80。"""
    record = PerformanceRecord(
        content_id=1, likes=500, comments=200, shares=100, views=10000
    )
    score = engine.calculate_score(record)
    assert score >= 80.0


def test_calculate_score_low_engagement(engine):
    """低互动数据，分数应 < 15。"""
    record = PerformanceRecord(content_id=1, likes=1, comments=0, shares=0, views=5)
    score = engine.calculate_score(record)
    assert score < 15.0


def test_calculate_score_capped_at_100(engine):
    """评分不应超过 100。"""
    record = PerformanceRecord(
        content_id=1, likes=100000, comments=100000, shares=100000, views=1000000
    )
    score = engine.calculate_score(record)
    assert score == 100.0


def test_calculate_score_formula_correctness(engine):
    """验证评分公式的正确性：min(100, log2(1 + raw) * 10)。"""
    record = PerformanceRecord(content_id=1, likes=10, comments=5, shares=2, views=100)
    score = engine.calculate_score(record)
    # raw = 10*1.0 + 5*3.0 + 2*5.0 + 100*0.1 = 45.0
    expected = min(100.0, math.log2(1 + 45.0) * 10)
    assert abs(score - expected) < 1e-9


# ---------------------------------------------------------------------------
# determine_frequency 测试
# ---------------------------------------------------------------------------

def test_determine_frequency_high(engine):
    """分数 >= 80 应返回 HIGH。"""
    assert engine.determine_frequency(80.0) == Frequency.HIGH
    assert engine.determine_frequency(95.0) == Frequency.HIGH
    assert engine.determine_frequency(100.0) == Frequency.HIGH


def test_determine_frequency_normal(engine):
    """分数 >= 40 且 < 80 应返回 NORMAL。"""
    assert engine.determine_frequency(40.0) == Frequency.NORMAL
    assert engine.determine_frequency(60.0) == Frequency.NORMAL
    assert engine.determine_frequency(79.9) == Frequency.NORMAL


def test_determine_frequency_low(engine):
    """分数 >= 15 且 < 40 应返回 LOW。"""
    assert engine.determine_frequency(15.0) == Frequency.LOW
    assert engine.determine_frequency(25.0) == Frequency.LOW
    assert engine.determine_frequency(39.9) == Frequency.LOW


def test_determine_frequency_paused(engine):
    """分数 < 15 应返回 PAUSED。"""
    assert engine.determine_frequency(0.0) == Frequency.PAUSED
    assert engine.determine_frequency(10.0) == Frequency.PAUSED
    assert engine.determine_frequency(14.9) == Frequency.PAUSED


# ---------------------------------------------------------------------------
# evaluate_content 测试
# ---------------------------------------------------------------------------

def test_evaluate_content(engine):
    """完整评估应返回包含正确字段的 ScoreResult。"""
    record = PerformanceRecord(
        content_id=42, likes=10, comments=5, shares=2, views=100
    )
    result = engine.evaluate_content(record)

    assert isinstance(result, ScoreResult)
    assert result.content_id == 42
    assert 0.0 <= result.score <= 100.0
    assert isinstance(result.recommended_frequency, Frequency)

    # 验证 score 和 frequency 的一致性
    expected_freq = engine.determine_frequency(result.score)
    assert result.recommended_frequency == expected_freq


def test_evaluate_content_zero(engine):
    """零互动记录的完整评估。"""
    record = PerformanceRecord(content_id=1, likes=0, comments=0, shares=0, views=0)
    result = engine.evaluate_content(record)

    assert result.content_id == 1
    assert result.score == 0.0
    assert result.recommended_frequency == Frequency.PAUSED


def test_evaluate_content_score_is_rounded(engine):
    """评估结果中的 score 应保留两位小数。"""
    record = PerformanceRecord(content_id=1, likes=10, comments=5, shares=2, views=100)
    result = engine.evaluate_content(record)
    # score 被 round(..., 2) 处理
    assert result.score == round(result.score, 2)


# ---------------------------------------------------------------------------
# batch_evaluate 测试
# ---------------------------------------------------------------------------

def test_batch_evaluate(engine):
    """批量评估多条记录，返回数量与输入一致且顺序对应。"""
    records = [
        PerformanceRecord(content_id=1, likes=0, comments=0, shares=0, views=0),
        PerformanceRecord(content_id=2, likes=10, comments=5, shares=2, views=100),
        PerformanceRecord(content_id=3, likes=500, comments=200, shares=100, views=10000),
    ]
    results = engine.batch_evaluate(records)

    assert len(results) == 3
    assert all(isinstance(r, ScoreResult) for r in results)

    # 验证 content_id 顺序
    assert results[0].content_id == 1
    assert results[1].content_id == 2
    assert results[2].content_id == 3

    # 验证不同互动水平产生不同的频率
    assert results[0].recommended_frequency == Frequency.PAUSED
    assert results[2].score >= 80.0


def test_batch_evaluate_empty(engine):
    """空列表输入应返回空列表。"""
    results = engine.batch_evaluate([])
    assert results == []


# ---------------------------------------------------------------------------
# 自定义权重测试
# ---------------------------------------------------------------------------

def test_custom_weights():
    """使用自定义权重时，评分结果应随权重变化。"""
    record = PerformanceRecord(content_id=1, likes=100, comments=0, shares=0, views=0)

    # 默认权重：likes=1.0
    default_engine = ScoringEngine()
    default_score = default_engine.calculate_score(record)

    # 自定义权重：likes=10.0（大幅提高 likes 权重）
    custom_weights = {"likes": 10.0, "comments": 3.0, "shares": 5.0, "views": 0.1}
    custom_engine = ScoringEngine(weights=custom_weights)
    custom_score = custom_engine.calculate_score(record)

    # 自定义权重下的分数应更高
    assert custom_score > default_score


def test_custom_thresholds():
    """使用自定义阈值时，频率判定应按新阈值执行。"""
    custom_thresholds = {"high": 90.0, "normal": 60.0, "low": 30.0}
    engine = ScoringEngine(thresholds=custom_thresholds)

    # 在默认阈值下 80 是 HIGH，但自定义阈值下应为 NORMAL
    assert engine.determine_frequency(80.0) == Frequency.NORMAL
    # 在默认阈值下 50 是 NORMAL，但自定义阈值下应为 LOW
    assert engine.determine_frequency(50.0) == Frequency.LOW
    # 90 在自定义阈值下是 HIGH
    assert engine.determine_frequency(90.0) == Frequency.HIGH
    # 20 在自定义阈值下是 PAUSED
    assert engine.determine_frequency(20.0) == Frequency.PAUSED


def test_custom_weights_and_thresholds_combined():
    """同时自定义权重和阈值。"""
    custom_weights = {"likes": 0.0, "comments": 0.0, "shares": 0.0, "views": 1.0}
    custom_thresholds = {"high": 50.0, "normal": 30.0, "low": 10.0}
    engine = ScoringEngine(weights=custom_weights, thresholds=custom_thresholds)

    # 只有 views 有权重
    record = PerformanceRecord(content_id=1, likes=999, comments=999, shares=999, views=0)
    score = engine.calculate_score(record)
    assert score == 0.0  # views=0 且只有 views 有权重，所以分数为 0
