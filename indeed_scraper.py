import configparser
import json
import logging
import os
import random
import re
import time
from pathlib import Path

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

VERIFICATION_TEXT = re.compile(
    r"^(Additional Verification Required|Verify you are human|"
    r"Checking your browser.*|Just a moment.*)$", re.I
)

def human_delay(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


def verification_required():
    # Inspect visible text, rather than matching words in scripts or job adverts.
    return page.get_by_text(VERIFICATION_TEXT).filter(visible=True).count() > 0


def capture_verification_diagnostics(attempt, stage, click_error=None):
    """Save inspection evidence; diagnostic failures must not stop scraping."""
    # These are the same selectors used by the existing click attempt below.
    iframe_selector = "iframe[src*='challenges'], iframe[src*='turnstile'], iframe[title*='challenge']"
    click_selector = "input[type='checkbox'], .cb-lb, #challenge-stage"
    try:
        directory = Path("data")
        directory.mkdir(parents=True, exist_ok=True)
        prefix = f"indeed_verification_attempt_{attempt}_{stage}"
        report = {
            "attempt": attempt,
            "stage": stage,
            "page_url": page.url,
            "iframe_selector": iframe_selector,
            "click_selector": click_selector,
            "click_error": click_error,
            "frames": [],
            "errors": [],
        }
        try:
            (directory / f"{prefix}_page.html").write_text(page.content(), encoding="utf-8")
        except Exception as error:
            report["errors"].append(f"Main page HTML: {type(error).__name__}: {error}")

        report["iframe_count"] = page.locator("iframe").count()
        report["matching_iframe_count"] = page.locator(iframe_selector).count()
        logger.info(
            "Indeed diagnostics (%s, attempt %s): %s iframe(s), %s match the existing iframe selector",
            stage, attempt, report["iframe_count"], report["matching_iframe_count"],
        )
        for index, frame in enumerate(page.frames):
            if frame == page.main_frame:
                continue
            details = {"index": index, "url": frame.url, "name": frame.name, "errors": []}
            report["frames"].append(details)
            try:
                details["iframe_element"] = frame.frame_element().evaluate(
                    """(element, selector) => ({
                        src: element.getAttribute('src'),
                        title: element.getAttribute('title'),
                        id: element.getAttribute('id'),
                        outer_html: element.outerHTML,
                        matches_existing_selector: element.matches(selector)
                    })""", iframe_selector
                )
            except Exception as error:
                details["errors"].append(f"Iframe attributes: {type(error).__name__}: {error}")
            try:
                html_file = f"{prefix}_frame_{index}.html"
                (directory / html_file).write_text(frame.content(), encoding="utf-8")
                details["html_file"] = html_file
            except Exception as error:
                details["errors"].append(f"Frame HTML: {type(error).__name__}: {error}")
            try:
                details["selector_counts"] = {
                    selector: frame.locator(selector).count()
                    for selector in ("input[type='checkbox']", ".cb-lb", "#challenge-stage", click_selector)
                }
                logger.info("Indeed diagnostics frame %s: selector counts %s", index, details["selector_counts"])
            except Exception as error:
                details["errors"].append(f"Selector counts: {type(error).__name__}: {error}")

        report_path = directory / f"{prefix}_report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Indeed: Verification diagnostics saved to %s", report_path)
    except Exception:
        logger.warning("Indeed: Could not save verification diagnostics", exc_info=True)


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
                page.goto(search_url, wait_until="networkidle")
                human_delay(2, 4)

                # Detect and solve Cloudflare challenge if present
                for attempt in range(3):
                    if verification_required():
                        logger.info(f"Indeed: Cloudflare challenge detected (attempt {attempt + 1}/3)")
                        os.makedirs("./data", exist_ok=True)
                        page.screenshot(path=f"./data/indeed_cf_attempt_{attempt}.png", full_page=True)
                        capture_verification_diagnostics(attempt, "before_click")

                        # Try clicking the Turnstile checkbox inside its iframe
                        click_error = None
                        try:
                            cf_iframe = page.frame_locator("iframe[src*='challenges'], iframe[src*='turnstile'], iframe[title*='challenge']")
                            cf_iframe.locator("input[type='checkbox'], .cb-lb, #challenge-stage").first.click(timeout=5000)
                            logger.info("Indeed: Clicked Cloudflare checkbox")
                        except Exception as e:
                            click_error = f"{type(e).__name__}: {e}"
                            # Sometimes there's no checkbox — just wait for auto-solve
                            logger.info("Indeed: Could not click verification checkbox (%s), waiting...", e)
                        capture_verification_diagnostics(attempt, "after_click", click_error)

                        # Wait for Cloudflare to process
                        human_delay(5, 10)
                        page.wait_for_load_state("networkidle")

                        # If still on challenge, try clicking anywhere in the page body
                        if verification_required():
                            page.mouse.click(random.randint(400, 600), random.randint(300, 500))
                            human_delay(3, 6)
                            page.wait_for_load_state("networkidle")
                    else:
                        break

                human_delay(1, 3)
            except Exception as e:
                logger.error(f"Indeed: Search flow failed — {e}")
                raise

            job_cards = page.locator(SELECTORS["job_cards"]).filter(visible=True)
            count = job_cards.count()
            if count == 0:
                logger.warning("Indeed: No job cards found after search")
                # Save screenshot so we can see what Indeed is actually showing
                os.makedirs("./data", exist_ok=True)
                page.screenshot(path="./data/indeed_debug.png", full_page=True)
                logger.info("Indeed: Debug screenshot saved to ./data/indeed_debug.png")

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
