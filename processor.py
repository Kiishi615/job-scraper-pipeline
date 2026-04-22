import configparser
import hashlib
import json
import logging
import os

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

logger = logging.getLogger(__name__)

config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(__file__), "pipeline.cfg"))


def _job_hash(job: dict) -> str:
    """Create a stable hash from raw job data for dedup."""
    key = f"{job.get('title', '')}|{job.get('employer', '')}|{job.get('source', '')}".lower()
    return hashlib.md5(key.encode()).hexdigest()


def _load_sent_hashes() -> set:
    """Load previously sent job hashes."""
    hashes_file = config.get("pipeline", "sent_hashes_file", fallback="sent_hashes.json")
    try:
        with open(hashes_file, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_sent_hashes(hashes: set):
    """Save sent job hashes."""
    hashes_file = config.get("pipeline", "sent_hashes_file", fallback="sent_hashes.json")
    with open(hashes_file, "w") as f:
        json.dump(list(hashes), f)


def processor(jobs_file):
    formatted_file = config.get("pipeline", "formatted_file", fallback="formatted.json")

    try:
        model = init_chat_model(model="gpt-5-mini")
    except Exception as e:
        logger.error(f"Failed to initialize chat model — {e}")
        raise

    try:
        with open(f"{jobs_file}", "r") as f:
            JOB_LISTING = json.load(f)
    except FileNotFoundError:
        logger.error(f"{jobs_file} not found — did merge run?")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"{jobs_file} contains invalid JSON — {e}")
        raise

    if not JOB_LISTING:
        logger.warning("Job listing is empty — nothing to process")
        return

    # Dedup: filter out jobs we've already sent
    sent_hashes = _load_sent_hashes()
    new_jobs = []
    for job in JOB_LISTING:
        h = _job_hash(job)
        if h not in sent_hashes:
            new_jobs.append(job)
        else:
            logger.debug(f"Skipping already-sent job: {job.get('title', '?')} @ {job.get('employer', '?')}")

    if not new_jobs:
        logger.info(f"All {len(JOB_LISTING)} jobs have already been sent — nothing new to process")
        # Write empty formatted file so notifier doesn't send stale data
        with open(formatted_file, "w") as f:
            json.dump([], f)
        return

    logger.info(f"Processing {len(new_jobs)} new jobs (skipped {len(JOB_LISTING) - len(new_jobs)} already-sent)")

    try:
        formatted = model.batch([f"""
                Format this job listing for Telegram:

                🏢 Company name
                💼 Job title
                📍 Location | Job type
                💰 Pay
                📋 Source: {job.get("source", "unknown")}

                2-3 sentence summary of what the role actually involves.
                Keep the entire formatted output under 2000 characters.
                use simple and clear words
                Job data: {job}
                """for job in new_jobs])
    except Exception as e:
        logger.error(f"LLM batch processing failed — {e}", exc_info=True)
        raise

    try:
        results = []
        new_hashes = []
        for job_data, job_response in zip(new_jobs, formatted):
            if job_response.content is not None:
                results.append(job_response.content[:2000])
                new_hashes.append(_job_hash(job_data))
            else:
                logger.warning("LLM returned None content for a job — skipping")
                results.append("⚠️ Failed to format this listing")

        with open(formatted_file, "w") as f:
            json.dump(results, f, indent=2)

        # Update sent hashes with newly processed jobs
        sent_hashes.update(new_hashes)
        _save_sent_hashes(sent_hashes)
        logger.info(f"Updated sent_hashes with {len(new_hashes)} new entries (total: {len(sent_hashes)})")

    except OSError as e:
        logger.error(f"Failed to write {formatted_file} — {e}")
        raise

    logger.info(f"Processed {len(results)} jobs successfully")


if __name__ == "__main__":
    processor("merged.json")