import configparser
import json
import logging
import os

logger = logging.getLogger(__name__)

config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(__file__), "pipeline.cfg"))


def merge(sources):
    merged_file = config.get("pipeline", "merged_file", fallback="merged.json")
    merged = []

    for filename in sources:
        try:
            with open(filename, "r") as f:
                jobs = json.load(f)
                merged.extend(jobs)
        except FileNotFoundError:
            logger.warning(f"{filename} not found, skipping")
        except json.JSONDecodeError as e:
            logger.error(f"{filename} contains invalid JSON, skipping — {e}")

    if not merged:
        logger.warning("Merge produced 0 jobs — all source files were empty or missing")

    try:
        with open(merged_file, "w") as f:
            json.dump(merged, f, indent=2)
    except OSError as e:
        logger.error(f"Failed to write {merged_file} — {e}")
        raise

    logger.info(f"Merged {len(merged)} jobs from {sources}")
    return merged    