import logging
import signal
import sys
import time

import schedule

from main import run

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("/app/data/pipeline.log"),
        logging.StreamHandler()
    ]
)


def graceful_shutdown(signum, frame):
    logger.info("Received shutdown signal — exiting gracefully")
    sys.exit(0)

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)


def job():
    logger.info("=" * 60)
    logger.info("Starting scheduled pipeline run")
    logger.info("=" * 60)
    try:
        run()
        logger.info("Pipeline run completed successfully")
    except Exception as e:
        logger.error(f"Pipeline run failed — {e}", exc_info=True)


# 7:30 AM WAT — catches Nigeria + UK/EU morning posts
# Results land in Telegram by ~7:45 AM, before 8 AM
schedule.every().day.at("06:30", "UTC").do(job)  # 6:30 UTC = 7:30 WAT

# 4:00 PM WAT — catches US East Coast morning posts
schedule.every().day.at("15:00", "UTC").do(job)  # 15:00 UTC = 16:00 WAT

logger.info("Scheduler started")
logger.info("  Run 1: 07:30 WAT (06:30 UTC) — Nigeria + UK/EU")
logger.info("  Run 2: 16:00 WAT (15:00 UTC) — US East Coast")

# Run immediately on first deploy so you don't wait until next scheduled time
job()

while True:
    schedule.run_pending()
    time.sleep(60)
