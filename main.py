import configparser
import logging
import os

from indeed_scraper import indeed_scraper
from jobberman_scraper import jobberman_scraper
from linkedin_scraper import linkedin_scraper
from merge import merge
from notifyer import notifier
from processor import processor

logger = logging.getLogger(__name__)


def _setup_logging():
    """Configure logging — only when running main.py directly (not via scheduler)."""
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
            handlers=[
                logging.FileHandler("pipeline.log"),
                logging.StreamHandler()
            ]
        )

config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(__file__), "pipeline.cfg"))

SCRAPERS = {
    "indeed": ("indeed", lambda: indeed_scraper(), config.get("indeed", "output_file", fallback="indeed_jobs.json")),
    "jobberman": ("jobberman", lambda: jobberman_scraper(), config.get("jobberman", "output_file", fallback="jobberman_jobs.json")),
    "linkedin": ("linkedin", lambda: linkedin_scraper(), config.get("linkedin", "output_file", fallback="linkedin_jobs.json")),
}

def run(sources=None):
    if sources is None:
        sources = ["indeed", "jobberman", "linkedin"]

    merged_file = config.get("pipeline", "merged_file", fallback="merged.json")
    files = []

    for name in sources:
        if name not in SCRAPERS:
            logger.warning(f"Unknown source: {name}")
            continue
        label, scraper, filename = SCRAPERS[name]
        try:
            logger.info(f"Running {label}...")
            scraper()
            files.append(filename)
            logger.info(f"{label} completed successfully")
        except Exception as e:
            logger.error(f"{label} scraper failed — {e}", exc_info=True)
            # Continue to next scraper instead of killing the pipeline

    if not files:
        logger.error("All scrapers failed — nothing to merge. Aborting pipeline.")
        return

    try:
        merge(files)
    except Exception as e:
        logger.error(f"Merge failed — {e}", exc_info=True)
        return

    try:
        processor(merged_file)
    except Exception as e:
        logger.error(f"Processor failed — {e}", exc_info=True)
        return

    try:
        notifier()
    except Exception as e:
        logger.error(f"Notifier failed — {e}", exc_info=True)
        # Data is already saved, so this is non-fatal
        logger.info("Scraping and processing completed, but notifications failed")

if __name__ == "__main__":
    _setup_logging()
    run()