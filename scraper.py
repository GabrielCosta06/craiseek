from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from alerts import AlertService
from config import get_settings
from db import Listing, insert_listing, list_unnotified_listings

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def parse_listings(html: str, base_url: str) -> List[Listing]:
    """Parse Craigslist HTML into Listing objects."""
    soup = BeautifulSoup(html, "lxml")
    listings: List[Listing] = []
    seen: set[str] = set()

    for item in soup.select("[data-pid]"):
        post_id = item.get("data-pid")
        if not post_id:
            continue
        if post_id in seen:
            continue
        seen.add(post_id)

        title_element = item.select_one(".result-title")
        anchor = title_element or item.find("a")
        title = anchor.get_text(strip=True) if anchor else ""

        price_element = item.select_one(".result-price")
        price = price_element.get_text(strip=True) if price_element else None

        hood_element = item.select_one(".result-hood")
        neighborhood = hood_element.get_text(strip=True) if hood_element else None
        if neighborhood:
            neighborhood = neighborhood.strip(" ()")

        href = anchor["href"] if anchor and anchor.has_attr("href") else None
        if not href:
            logger.warning("Listing missing URL", extra={"post_id": post_id})
        url = urljoin(base_url, href) if href else base_url

        if not title:
            logger.warning("Listing missing title", extra={"post_id": post_id})
            title = "Craigslist Listing"

        listings.append(
            Listing(
                post_id=post_id,
                title=title,
                price=price,
                neighborhood=neighborhood if neighborhood else None,
                url=url,
            )
        )

    return listings


def fetch_html(session: requests.Session, url: str, timeout: int, max_backoff: int) -> Optional[str]:
    """Fetch HTML content with exponential backoff and jitter."""
    max_attempts = 5
    base_delay = 5

    for attempt in range(1, max_attempts + 1):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            time.sleep(random.uniform(1, 3))
            return response.text
        except requests.RequestException as exc:
            wait_seconds = min(max_backoff, base_delay * (2 ** (attempt - 1)))
            logger.warning(
                "Request failed; backing off",
                extra={
                    "attempt": attempt,
                    "wait_seconds": wait_seconds,
                    "error": str(exc),
                },
            )
            if attempt == max_attempts:
                logger.error("Max retries reached; giving up on fetch.")
                return None
            time.sleep(wait_seconds + random.uniform(0, 1))
    return None


def run_once(alert_service: AlertService) -> None:
    settings = get_settings()
    if not settings.target_url:
        logger.error("TARGET_URL must be configured before running the scraper.")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": settings.user_agent})

    html = fetch_html(
        session=session,
        url=settings.target_url,
        timeout=settings.request_timeout_seconds,
        max_backoff=settings.max_backoff_seconds,
    )
    if not html:
        return

    parsed_listings = parse_listings(html, settings.target_url)
    if not parsed_listings:
        logger.info("No listings found on page.")
        return

    new_listings: List[Listing] = []
    for listing in parsed_listings:
        if insert_listing(listing):
            new_listings.append(listing)

    logger.info(
        "Scrape cycle complete",
        extra={"fetched": len(parsed_listings), "inserted": len(new_listings)},
    )

    pending_notifications = list_unnotified_listings(limit=None)
    if not pending_notifications:
        logger.info("No pending alerts to send.")
        return

    sent = alert_service.send_alerts(pending_notifications)
    logger.info("Alert run complete", extra={"alerts_sent": sent})


def main(argv: Optional[List[str]] = None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Craigslist rental scraper.")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["run", "once"],
        help="Optional command; defaults to run (looping mode).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the scraper one time and exit.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    alert_service = AlertService(settings=settings)

    if args.once or args.command == "once":
        run_once(alert_service)
        return

    logger.info("Starting scraper loop", extra={"interval_seconds": settings.scrape_interval_seconds})
    try:
        while True:
            start = time.time()
            run_once(alert_service)
            elapsed = time.time() - start
            sleep_for = max(0, settings.scrape_interval_seconds - elapsed)
            if sleep_for:
                logger.info("Sleeping before next scrape", extra={"seconds": round(sleep_for, 2)})
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        logger.info("Scraper interrupted by user.")


if __name__ == "__main__":
    main(sys.argv[1:])
