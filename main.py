"""
内容自动调度系统 -- 入口
使用 APScheduler 驱动周期性调度循环。
"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from apscheduler.schedulers.blocking import BlockingScheduler
from config import DB_PATH, SCHEDULE_INTERVAL_SECONDS
from models.database import init_database
from agents.scheduler import Scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    init_database(DB_PATH)
    logger.info("Database initialized at %s", DB_PATH)

    scheduler_agent = Scheduler(DB_PATH)

    ap_scheduler = BlockingScheduler()
    ap_scheduler.add_job(
        scheduler_agent.run_cycle,
        trigger="interval",
        seconds=SCHEDULE_INTERVAL_SECONDS,
        id="content_schedule_cycle",
    )

    logger.info(
        "Scheduler started. Cycle interval: %d seconds",
        SCHEDULE_INTERVAL_SECONDS,
    )

    # Run one cycle immediately
    stats = scheduler_agent.run_cycle()
    logger.info("Initial cycle completed: %s", stats)

    try:
        ap_scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")
        ap_scheduler.shutdown()


if __name__ == "__main__":
    main()
