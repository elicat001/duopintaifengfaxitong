"""
智能评分引擎模块

纯计算模块，不访问数据库。
根据内容的表现数据（likes, comments, shares, views）计算加权评分，
并根据评分结果推荐投放频率。
"""

import math
from typing import List

from models.schemas import Frequency, PerformanceRecord, ScoreResult
from config import SCORE_WEIGHTS, SCORE_THRESHOLDS


class ScoringEngine:
    """智能评分引擎，根据内容表现数据计算评分并推荐投放频率。"""

    def __init__(self, weights: dict = None, thresholds: dict = None):
        """
        初始化评分引擎。

        Args:
            weights: 评分权重字典，包含 likes/comments/shares/views 的权重。
                     如果为 None，则使用 config.py 中的默认权重。
            thresholds: 频率阈值字典，包含 high/normal/low 的阈值。
                        如果为 None，则使用 config.py 中的默认阈值。
        """
        self.weights = weights if weights is not None else dict(SCORE_WEIGHTS)
        self.thresholds = thresholds if thresholds is not None else dict(SCORE_THRESHOLDS)

    def calculate_score(self, record: PerformanceRecord) -> float:
        """
        计算单条记录的加权评分。

        使用对数缩放公式将原始加权和映射到 0-100 分范围内。

        Args:
            record: 包含 likes, comments, shares, views 的表现记录。

        Returns:
            评分结果，范围 0.0 ~ 100.0。
        """
        raw = (
            record.likes * self.weights["likes"]
            + record.comments * self.weights["comments"]
            + record.shares * self.weights["shares"]
            + record.views * self.weights["views"]
        )
        return min(100.0, math.log2(1 + raw) * 10)

    def determine_frequency(self, score: float) -> Frequency:
        """
        根据评分确定推荐的投放频率。

        频率判定规则：
        - score >= 80 -> HIGH（每天投放）
        - score >= 40 -> NORMAL（每3天投放）
        - score >= 15 -> LOW（每7天投放）
        - score < 15  -> PAUSED（暂停投放）

        Args:
            score: 评分，范围 0.0 ~ 100.0。

        Returns:
            推荐的投放频率枚举值。
        """
        if score >= self.thresholds["high"]:
            return Frequency.HIGH
        elif score >= self.thresholds["normal"]:
            return Frequency.NORMAL
        elif score >= self.thresholds["low"]:
            return Frequency.LOW
        else:
            return Frequency.PAUSED

    def evaluate_content(self, record: PerformanceRecord) -> ScoreResult:
        """
        对单条表现记录进行完整评估。

        先计算评分，再根据评分确定推荐频率，最终返回完整的评估结果。

        Args:
            record: 包含内容表现数据的记录。

        Returns:
            包含 content_id、score、recommended_frequency 的评估结果。
        """
        score = self.calculate_score(record)
        frequency = self.determine_frequency(score)
        return ScoreResult(
            content_id=record.content_id,
            score=round(score, 2),
            recommended_frequency=frequency,
        )

    def batch_evaluate(self, records: List[PerformanceRecord]) -> List[ScoreResult]:
        """
        批量评估多条表现记录。

        Args:
            records: 表现记录列表。

        Returns:
            评估结果列表，与输入记录一一对应。
        """
        return [self.evaluate_content(record) for record in records]
