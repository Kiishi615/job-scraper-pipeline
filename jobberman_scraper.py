import configparser
import json
import logging
import os
import random
import re
import time

from playwright.sync_api import expect, sync_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

page = None

SELECTORS = {
    "remote_option": "Remote (Work From Home)",
    "search_box": "Search title, keywords or company",
    "location_box": "Location",
    "search_btn": "Search",
    "job_function_btn": "Job function",
    "software_data_link": re.compile(r"^Software & Data \(\d+\)$", re.I),
    "job_cards": 'h3 a[href*="/listings/"]',
    "job_title": 'h1[data-cy="title-job"]',
    "employer": "h2.text-base.leading-6.font-normal",
    "pay": "div.flex-wrap.gap-x-6 span.inline-flex",
    "summary": "p.mt-4.text-sm",
    "requirements": "div.flex.mt-6",
    "full_description": "div.prose",
    "location_and_type": "div.flex-wrap.gap-x-6 a",
}

def human_delay(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


def search_jobs(search_term: str):
    # Desktop and mobile forms share placeholders; target the visible fields.
    page.get_by_placeholder(SELECTORS["search_box"], exact=True).filter(visible=True).fill(search_term)
    page.get_by_placeholder(SELECTORS["location_box"], exact=True).filter(visible=True).fill("Remote")
    page.get_by_role("button", name=SELECTORS["remote_option"], exact=True).filter(visible=True).click()
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.get_by_role("button", name=SELECTORS["search_btn"], exact=True).filter(visible=True).click()

    job_function = page.get_by_role("button", name=SELECTORS["job_function_btn"], exact=True)
    # Alpine adds aria-expanded when the menu is interactive. Clicking before
    # initialization can be ignored even though the button is already visible.
    expect(job_function).to_have_attribute("aria-expanded", "false", timeout=15000)
    job_function.click()
    # The filter label includes a result count. Card category links would reset
    # the keyword and remote filters, so match the dropdown option explicitly.
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.get_by_role("link", name=SELECTORS["software_data_link"]).filter(visible=True).click()
    page.locator("h1").first.wait_for(state="visible")


def collector(tag: str) -> str | None:
    try:
        page.wait_for_selector(tag, timeout=5000) # type: ignore
        contents = page.locator(tag).all_inner_texts() # type: ignore
        if not contents:
            return None
        merged = " ".join(contents)
        return merged
    except Exception:
        return None

def get_location_and_job_type(tag: str):
    try:
        page.wait_for_selector(tag, timeout=5000) # type: ignore
        contents = page.locator(tag).all_inner_texts() # type: ignore
        location = contents[0] if len(contents) > 0 else None
        job_type = contents[1] if len(contents) > 1 else None
        return location, job_type
    except Exception:
        return None, None

def jobberman_scraper():
    global page
    jobs = []

    config = configparser.ConfigParser()
    config.read(os.path.join(os.path.dirname(__file__), "pipeline.cfg"))
    search_term = config.get("jobberman", "search_term", fallback="AI")
    user_data_dir = config.get("jobberman", "user_data_dir", fallback=r"C:\Users\Audit\firefox_jobberman_profile")
    output_file = config.get("jobberman", "output_file", fallback="jobberman_jobs.json")

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
                page.goto("https://www.jobberman.com/", wait_until="domcontentloaded")

                human_delay(2, 5)

                # Dismiss cookie consent (blocks clicks on fresh browser/CI)
                try:
                    page.locator("#onetrust-accept-btn-handler").click(timeout=5000)
                    human_delay(1, 2)
                except Exception:
                    pass

                page.mouse.move(random.randint(200, 600), random.randint(200, 500))
                human_delay()

                search_jobs(search_term)
                human_delay()
            except Exception as e:
                logger.error(f"Jobberman: Search/filter flow failed — {e}")
                raise

            job_cards = page.locator(SELECTORS["job_cards"]).filter(visible=True)
            count = job_cards.count()

            if count == 0:
                logger.warning("Jobberman: No job cards found after search")

            logger.info(f"Jobberman: Found {count} jobs")
            for i in range(count):
                try:
                    # Re-query locator after each go_back to avoid stale references
                    job_cards = page.locator(SELECTORS["job_cards"]).filter(visible=True)
                    job_cards.nth(i).click()
                    page.wait_for_load_state("domcontentloaded")
                    human_delay(2, 4)

                    job_title = collector(SELECTORS["job_title"])
                    if job_title:
                        job_title = job_title.replace(" *", "")
                    try:
                        employer = page.locator(SELECTORS["employer"]).first.inner_text()
                    except Exception as e:
                        logger.warning(f"Jobberman: Employer not found for card {i} — {e}")
                        employer = None
                    pay = collector(SELECTORS["pay"])

                    summary = collector(SELECTORS["summary"])
                    requirements = collector(SELECTORS["requirements"])
                    full_desc = collector(SELECTORS["full_description"])
                    # Build description only from parts that were actually found
                    desc_parts = [p for p in [summary, requirements, full_desc] if p is not None]
                    description = "Job Summary\n" + "\n".join(desc_parts) if desc_parts else None

                    location, job_type = get_location_and_job_type(SELECTORS["location_and_type"])
                    
                    jobs.append(
                            {
                                "title": job_title,
                                "employer": employer,
                                "job type": job_type,
                                "description": description,
                                "pay": pay,
                                "location": location,
                                "source": "Jobberman"
                            }
                        )
                except Exception as e:
                    logger.error(f"Jobberman: Failed to scrape card {i} — {e}")
                    try:
                        page.go_back(wait_until="domcontentloaded")
                    except Exception:
                        logger.error(f"Jobberman: go_back() also failed after card {i} error")
                    continue
                human_delay(2, 4)

                try:
                    page.go_back(wait_until="domcontentloaded")
                except Exception as e:
                    logger.error(f"Jobberman: go_back() failed after card {i} — {e}")
                    break

        JOBS = [job for job in jobs if job['description'] is not None]
        try:
            tmp_file = output_file + ".tmp"
            with open(tmp_file, "w") as f:
                json.dump(JOBS, f, indent=2)
            if JOBS:
                os.replace(tmp_file, output_file)
                logger.info(f"Jobberman: Wrote {len(JOBS)} jobs to {output_file}")
            else:
                os.remove(tmp_file)
                logger.warning("Jobberman: No valid jobs scraped — previous output preserved")
        except OSError as e:
            logger.error(f"Jobberman: Failed to write output file — {e}")

    except Exception as e:
        logger.error(f"Jobberman: Scraper failed — {e}")
        raise

        
if __name__ == "__main__":
    jobberman_scraper()
