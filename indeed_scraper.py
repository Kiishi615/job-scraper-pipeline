import configparser
import json
import logging
import os
import random
import time

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

page = None

SELECTORS = {
    "search_what": "#text-input-what",
    "search_where": "#text-input-where",
    "job_cards": ".jcs-JobTitle",
    "job_title": ".jobsearch-JobInfoHeader-title",
    "employer": ".css-1h4l2d7",
    "description": "#jobDescriptionText",
    "job_type_and_pay": ".js-match-insights-provider-18uwqyc",
    "location": "#jobLocationText",
}

def human_delay(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))

def collector(tag: str) -> str | None:
    try:
        page.wait_for_selector(tag, timeout=5000)
        contents = page.locator(tag).all_inner_texts()
        if not contents:
            return None
        merged = " ".join(contents)
        return merged
    except Exception:
        return None

def get_job_type_and_pay(tag: str):
    try:
        page.wait_for_selector(tag, timeout=5000)
        contents = page.locator(tag).all_inner_texts()
        job_type, pay = None, None
        for content in contents:
            if "\u20a6" in content:
                pay = content
            else:
                job_type = content
        return job_type, pay
    except Exception:
        return None, None

def indeed_scraper():
    global page
    jobs = []

    config = configparser.ConfigParser()
    config.read(os.path.join(os.path.dirname(__file__), "pipeline.cfg"))
    search_term = config.get("indeed", "search_term", fallback="AI Engineer")
    location = config.get("indeed", "location", fallback="remote")
    user_data_dir = config.get("indeed", "user_data_dir", fallback=r"C:\Users\Audit\firefox_indeed_profile")
    output_file = config.get("indeed", "output_file", fallback="indeed_jobs.json")

    try:
        with sync_playwright() as p:
            context = p.firefox.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                slow_mo=500,
                viewport={"width": 1366, "height": 768},
                locale="en-GB",
                timezone_id="Africa/Lagos"
            )
            page = context.pages[0] if context.pages else context.new_page()
            Stealth().apply_stealth_sync(page)

            try:
                # Go directly to search results with desktop referrer
                search_url = f"https://ng.indeed.com/jobs?q={search_term.replace(' ', '%20')}&l={location}&from=searchOnDesktopSerp"
                page.goto(search_url)
                page.wait_for_load_state("networkidle")
                human_delay(2, 5)
            except Exception as e:
                logger.error(f"Indeed: Search flow failed — {e}")
                raise

            job_cards = page.locator(SELECTORS["job_cards"]).filter(visible=True)
            count = job_cards.count()
            if count == 0:
                logger.warning("Indeed: No job cards found after search")

            for i in range(count):
                try:
                    job_cards.nth(i).click()
                    job_title = collector(SELECTORS["job_title"])
                    if job_title:
                        job_title = job_title.replace("\n- job post", "")
                    employer = collector(SELECTORS["employer"])
                    description = collector(SELECTORS["description"])
                    job_type, pay = get_job_type_and_pay(SELECTORS["job_type_and_pay"])
                    location_text = collector(SELECTORS["location"])

                    jobs.append(
                        {
                            "title": job_title,
                            "employer": employer,
                            "job type": job_type,
                            "description": description,
                            "pay": pay,
                            "location": location_text,
                            "source": "Indeed"
                        }
                    )
                except Exception as e:
                    logger.error(f"Indeed: Failed to scrape card {i} — {e}")
                    continue
                human_delay(2, 4)

            JOBS = [job for job in jobs if job['description'] is not None]
            try:
                tmp_file = output_file + ".tmp"
                with open(tmp_file, "w") as f:
                    json.dump(JOBS, f, indent=2)
                if JOBS:
                    os.replace(tmp_file, output_file)
                    logger.info(f"Indeed: Wrote {len(JOBS)} jobs to {output_file}")
                else:
                    os.remove(tmp_file)
                    logger.warning("Indeed: No valid jobs scraped — previous output preserved")
            except OSError as e:
                logger.error(f"Indeed: Failed to write output file — {e}")

    except Exception as e:
        logger.error(f"Indeed: Browser launch/setup failed — {e}")
        raise

if __name__ == "__main__":
    indeed_scraper()
