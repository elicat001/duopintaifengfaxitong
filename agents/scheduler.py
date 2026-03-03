import logging
from datetime import datetime, timedelta
from typing import List

from models.database import get_connection
from models.schemas import SchedulePlan, Frequency, ScoreResult
from agents.performance_tracker import PerformanceTracker
from agents.scoring_engine import ScoringEngine

logger = logging.getLogger(__name__)

FREQUENCY_INTERVALS = {
    Frequency.HIGH: timedelta(days=1),
    Frequency.NORMAL: timedelta(days=3),
    Frequency.LOW: timedelta(days=7),
    Frequency.PAUSED: None,
}


class Scheduler:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_due_contents(self) -> List[SchedulePlan]:
        conn = get_connection(self.db_path)
        try:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                """
                SELECT * FROM schedule_plans
                WHERE frequency != ? AND next_publish_at <= ?
                """,
                (Frequency.PAUSED.value, now),
            )
            rows = cursor.fetchall()
            return [self._row_to_plan(row) for row in rows]
        finally:
            conn.close()

    def execute_publish(self, plan: SchedulePlan) -> bool:
        conn = get_connection(self.db_path)
        try:
            now = datetime.now()
            interval = FREQUENCY_INTERVALS.get(plan.frequency)
            next_publish = (now + interval) if interval else None

            conn.execute(
                """
                UPDATE schedule_plans
                SET last_published_at = ?,
                    next_publish_at = ?,
                    publish_count = publish_count + 1,
                    updated_at = ?
                WHERE content_id = ?
                """,
                (
                    now.isoformat(),
                    next_publish.isoformat() if next_publish else None,
                    now.isoformat(),
                    plan.content_id,
                ),
            )
            conn.commit()
            logger.info(
                "Published content_id=%d (count=%d, next=%s)",
                plan.content_id,
                plan.publish_count + 1,
                next_publish,
            )
            return True
        except Exception as e:
            logger.error("Failed to publish content_id=%d: %s", plan.content_id, e)
            return False
        finally:
            conn.close()

    def update_plan_from_score(self, result: ScoreResult) -> None:
        conn = get_connection(self.db_path)
        try:
            now = datetime.now()
            interval = FREQUENCY_INTERVALS.get(result.recommended_frequency)
            next_publish = (now + interval) if interval else None

            conn.execute(
                """
                UPDATE schedule_plans
                SET score = ?,
                    frequency = ?,
                    next_publish_at = ?,
                    updated_at = ?
                WHERE content_id = ?
                """,
                (
                    result.score,
                    result.recommended_frequency.value,
                    next_publish.isoformat() if next_publish else None,
                    now.isoformat(),
                    result.content_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def run_cycle(self) -> dict:
        tracker = PerformanceTracker(self.db_path)
        engine = ScoringEngine()
        stats = {"published": 0, "rescheduled": 0, "paused": 0}

        # Step 1: execute due publications
        due_plans = self.get_due_contents()
        for plan in due_plans:
            if self.execute_publish(plan):
                stats["published"] += 1

        # Step 2: re-score all active content
        latest_records = tracker.get_all_latest_records()
        score_results = engine.batch_evaluate(latest_records)

        # Step 3: update schedule plans based on scores
        for result in score_results:
            self.update_plan_from_score(result)
            if result.recommended_frequency == Frequency.PAUSED:
                stats["paused"] += 1
            else:
                stats["rescheduled"] += 1

        logger.info("Cycle completed: %s", stats)
        return stats

    @staticmethod
    def _row_to_plan(row) -> SchedulePlan:
        return SchedulePlan(
            id=row["id"],
            content_id=row["content_id"],
            score=row["score"],
            frequency=Frequency(row["frequency"]),
            next_publish_at=row["next_publish_at"],
            last_published_at=row["last_published_at"],
            publish_count=row["publish_count"],
            updated_at=row["updated_at"],
        )
