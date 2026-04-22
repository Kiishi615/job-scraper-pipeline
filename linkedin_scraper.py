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
    "search_box": "Search job titles or companies",
    "location_box": "Location",
    "search_btn": "Search",
    "experience_filter": "Experience level filter.",
    "entry_level": "Entry level",
    "date_filter": "Date posted filter. Any time",
    "past_24h": "Past 24 hours",
    "done_btn": "Done",
    "dismiss_btn": "Dismiss",
    "job_cards": "a.base-card__full-link",
    "show_more": "Show more",
    "job_title": "h2.top-card-layout__title",
    "description": "div.show-more-less-html__markup",
    "job_type": '[class*="job-criteria-text"]',
    "employer": "a.topcard__org-name-link",
    "location": "span.topcard__flavor--bullet",
}

def check_authwall():
    if "authwall" in page.url:
        logger.warning(f"LinkedIn: Authwall detected, navigating back")
        page.go_back()
        page.wait_for_load_state("domcontentloaded")
        human_delay(3, 6)
        return True
    return False

def dismiss_popup():
    try:
        popup = page.get_by_role("button", name=SELECTORS["dismiss_btn"])
        if popup.is_visible(timeout=1000):
            human_click(popup)
            human_delay(0.5, 1)
    except Exception:
        pass

def human_delay(a=1.5, b=3.5):
    """Wait like a human — move mouse, maybe scroll, pause irregularly."""
    # Split the wait into chunks instead of one solid block
    total = random.uniform(a, b)
    chunks = random.randint(2, 4)
    per_chunk = total / chunks

    for _ in range(chunks):
        time.sleep(per_chunk)
        # Random mouse movement — small drift, not huge jumps
        page.mouse.move(
            random.randint(100, 1200),
            random.randint(100, 600)
        )

    # Occasionally scroll a bit (30% chance)
    if random.random() < 0.3:
        page.mouse.wheel(0, random.randint(-200, 200))
        time.sleep(random.uniform(0.3, 0.8))

def human_click(target):
    """Move to element, maybe hesitate, then click."""
    try:
        box = target.bounding_box()
        if box:
            # Move to somewhere near the element first, not directly on it
            page.mouse.move(
                box["x"] + random.randint(-20, 20),
                box["y"] + random.randint(-20, 20)
            )
            time.sleep(random.uniform(0.2, 0.6))
            # Then move onto the element
            page.mouse.move(
                box["x"] + box["width"] / 2 + random.randint(-5, 5),
                box["y"] + box["height"] / 2 + random.randint(-5, 5)
            )
            time.sleep(random.uniform(0.1, 0.3))
        target.click()
    except Exception:
        target.click()

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


def linkedin_scraper():
    global page
    jobs = []

    config = configparser.ConfigParser()
    config.read(os.path.join(os.path.dirname(__file__), "pipeline.cfg"))
    search_term = config.get("linkedin", "search_term", fallback="AI Engineering")
    location_text = config.get("linkedin", "location", fallback="Remote")
    user_data_dir = config.get("linkedin", "user_data_dir", fallback=r"C:\Users\Audit\firefox_linkedin_profile")
    cookie_file = config.get("linkedin", "cookie_file", fallback="linkedin_cookies.json")
    output_file = config.get("linkedin", "output_file", fallback="linkedin_jobs.json")
    max_cards = config.getint("linkedin", "max_cards", fallback=15)

    try:
        with sync_playwright() as p:
            context = p.firefox.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                viewport={"width": 1366, "height": 768},
                locale="en-GB",
                timezone_id="Africa/Lagos"
            )
            page = context.pages[0] if context.pages else context.new_page()
            Stealth().apply_stealth_sync(page)

            try:
                with open(cookie_file, "r") as f:
                    cookies = json.load(f)
            except FileNotFoundError:
                logger.error(f"LinkedIn: {cookie_file} not found — cannot authenticate")
                raise
            except json.JSONDecodeError as e:
                logger.error(f"LinkedIn: {cookie_file} is malformed — {e}")
                raise

            formatted = []
            try:
                for c in cookies:
                    formatted.append({
                        "name": c["Name raw"],
                        "value": c["Content raw"],
                        "domain": c["Host raw"].replace("https://", "").replace("http://", "").rstrip("/"),
                        "path": c["Path raw"],
                    })
            except KeyError as e:
                logger.error(f"LinkedIn: Cookie format unexpected, missing key {e}")
                raise

            context.add_cookies(formatted)

            try:
                page.goto("https://www.linkedin.com/jobs/search?trk=guest_homepage-basic_guest_nav_menu_jobs")
                page.wait_for_load_state("domcontentloaded")
                
                dismiss_popup()
                human_delay(1, 3)

                dismiss_popup()
                human_click(page.get_by_role("combobox", name=SELECTORS["search_box"]))
                human_delay(0.5, 1.5)  # about to type
                page.get_by_role("combobox", name=SELECTORS["search_box"]).press_sequentially(search_term, delay=random.randint(80, 160))
                human_delay(0.5, 1)  # reading what I typed
                
                dismiss_popup()
                page.keyboard.press("Enter")
                page.wait_for_load_state("domcontentloaded")
                human_delay(2, 5)  # scanning results

                dismiss_popup()
                human_click(page.get_by_role("combobox", name=SELECTORS["location_box"]))
                human_delay(0.3, 1)  # about to type
                page.get_by_role("combobox", name=SELECTORS["location_box"]).clear()
                page.get_by_role("combobox", name=SELECTORS["location_box"]).press_sequentially(location_text, delay=random.randint(80, 160))
                human_delay(0.3, 0.8)  # reading what I typed
                page.keyboard.press("Enter")
                
                dismiss_popup()
                human_click(page.get_by_role("button", name=SELECTORS["search_btn"], exact=True))
                page.wait_for_load_state("domcontentloaded")
                human_delay(2, 5) 

                page.evaluate("window.scrollBy(0, 300)")
                human_delay(0.5, 1.5)  # scrolling down to find filters
                
                dismiss_popup()
                human_click(page.get_by_role("button", name=SELECTORS["experience_filter"]))
                human_delay(0.5, 1)  # reading options
                page.get_by_role("checkbox", name=SELECTORS["entry_level"]).check()
                human_delay(0.3, 0.8)  # made a selection
                
                dismiss_popup()
                human_click(page.get_by_role("button", name=SELECTORS["done_btn"]))
                page.wait_for_load_state("domcontentloaded")
                human_delay(2, 4)  # waiting for filtered results

                dismiss_popup()
                human_click(page.get_by_role("button", name=SELECTORS["date_filter"]))
                human_delay(0.5, 1)  # reading options
                page.get_by_role("radio", name=SELECTORS["past_24h"]).check()
                human_delay(0.3, 0.8)  # made a selection
                
                dismiss_popup()
                human_click(page.get_by_role("button", name=SELECTORS["done_btn"]))
                page.wait_for_load_state("domcontentloaded")
                human_delay(2, 4)
            except Exception as e:
                logger.error(f"LinkedIn: Search/filter flow failed — {e}")
                raise


            job_cards = page.locator(SELECTORS["job_cards"]).filter(visible=True)
            dismiss_popup()

            count = job_cards.count()
            if count == 0:
                logger.warning("LinkedIn: No job cards found after search")
            logger.info(f"LinkedIn: Found {count} job cards")

            consecutive_authwalls = 0
            for i in range(min(max_cards, count)):
                try:
                    job_cards.nth(i).click()
                    page.wait_for_load_state("domcontentloaded")
                    
                    if check_authwall():
                        consecutive_authwalls += 1
                        if consecutive_authwalls >= 3:
                            logger.error("LinkedIn: 3 consecutive authwall redirects — cookies likely expired. Aborting.")
                            break
                        continue
                    else:
                        consecutive_authwalls = 0

                    human_delay(2, 4)
                    page.wait_for_load_state("domcontentloaded")
                        
                    dismiss_popup()
                
                    try:
                        page.get_by_role("button", name=SELECTORS["show_more"]).click(timeout=3000)
                    except Exception:
                        pass

                    job_title = collector(SELECTORS["job_title"])
                    description = collector(SELECTORS["description"])
                    try:
                        job_type = page.locator(SELECTORS["job_type"]).nth(1).inner_text()
                    except Exception as e:
                        logger.warning(f"LinkedIn: job_type not found for card {i} — {e}")
                        job_type = None
                    employer = collector(SELECTORS["employer"])
                    location_val = collector(SELECTORS["location"])

                    jobs.append(
                                {
                                    "title": job_title,
                                    "employer": employer,
                                    "job type": job_type,
                                    "description": description,
                                    "location": location_val,
                                    "source": "Linkedin"
                                }
                            )
                except Exception as e:
                    logger.error(f"LinkedIn: Failed to scrape card {i} — {e}")
                    continue
                human_delay(2, 4)

            JOBS = [job for job in jobs if job['description'] is not None]
            try:
                tmp_file = output_file + ".tmp"
                with open(tmp_file, "w") as f:
                    json.dump(JOBS, f, indent=2)
                if JOBS:
                    os.replace(tmp_file, output_file)
                    logger.info(f"LinkedIn: Wrote {len(JOBS)} jobs to {output_file}")
                else:
                    os.remove(tmp_file)
                    logger.warning("LinkedIn: No valid jobs scraped — previous output preserved")
            except OSError as e:
                logger.error(f"LinkedIn: Failed to write output file — {e}")

    except Exception as e:
        logger.error(f"LinkedIn: Browser launch/setup failed — {e}")
        raise
