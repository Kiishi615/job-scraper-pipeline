import configparser
import json
import logging
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(__file__), "pipeline.cfg"))

def notifier():
    chat_id = config.get("telegram", "chat_id", fallback="953499438")
    formatted_file = config.get("pipeline", "formatted_file", fallback="formatted.json")
    bot_token = os.getenv("TELEGRAM_API_KEY")

    if not bot_token:
        logger.error("TELEGRAM_API_KEY not set in environment — cannot send notifications")
        raise ValueError("Missing TELEGRAM_API_KEY environment variable")

    try:
        with open(formatted_file, "r") as f:
            content = json.load(f)
    except FileNotFoundError:
        logger.error(f"{formatted_file} not found — did processor run?")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"{formatted_file} is malformed — {e}")
        raise

    if not content:
        logger.info("No messages to send — formatted file is empty (all jobs already sent)")
        return

    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'

    for idx, job in enumerate(content):
        payload = {
            'chat_id': chat_id,
            'text': job
        }

        sent = False
        for attempt in range(3):
            try:
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    logger.info(f"Message {idx+1}/{len(content)} sent successfully")
                    sent = True
                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 30))
                    logger.warning(f"Rate limited by Telegram, retrying in {retry_after}s (attempt {attempt+1}/3)")
                    time.sleep(retry_after)
                    continue
                elif response.status_code >= 500:
                    logger.warning(f"Telegram server error {response.status_code}, retrying (attempt {attempt+1}/3)")
                    time.sleep(5 * (attempt + 1))
                    continue
                else:
                    logger.error(f"Failed to send message {idx+1}: {response.status_code} — {response.text}")
                break
            except requests.exceptions.Timeout:
                logger.warning(f"Timed out, attempt {attempt + 1}/3...")
                time.sleep(5)
            except requests.exceptions.ConnectionError:
                logger.warning(f"Connection failed, attempt {attempt + 1}/3...")
                time.sleep(10)
            except requests.exceptions.RequestException as e:
                logger.error(f"Unexpected request error for message {idx+1} — {e}")
                break
        
        if not sent:
            logger.error(f"Gave up sending message {idx+1}/{len(content)} after 3 attempts")
        
        time.sleep(20)
        
if __name__ == "__main__":
    notifier()
