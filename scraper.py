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
    """Parse Facebook Marketplace HTML into Listing objects."""
    soup = BeautifulSoup(html, "lxml")
    listings: List[Listing] = []
    seen: set[str] = set()

    # Facebook Marketplace uses dynamic rendering, so parsing raw HTML is limited
    # This is a basic implementation that looks for common patterns
    # For production, consider using Facebook's Graph API or Selenium for dynamic content
    
    # Look for marketplace listing containers (these selectors may need adjustment)
    # Facebook's class names are often minified/obfuscated
    for item in soup.find_all(["div", "a"], attrs={"href": lambda x: x and "/marketplace/item/" in str(x)}):
        # Extract listing ID from URL
        href = item.get("href", "")
        if "/marketplace/item/" not in href:
            continue
            
        # Extract post ID from marketplace URL
        post_id_match = href.split("/marketplace/item/")[-1].split("/")[0].split("?")[0]
        if not post_id_match or post_id_match in seen:
            continue
        post_id = post_id_match
        seen.add(post_id)

        # Try to extract title - look for text in the link or nearby elements
        title = item.get_text(strip=True) if item.get_text(strip=True) else None
        if not title:
            # Try to find title in child elements
            title_candidates = item.find_all(["span", "div"], recursive=True)
            for candidate in title_candidates:
                text = candidate.get_text(strip=True)
                if text and len(text) > 5 and len(text) < 200:
                    title = text
                    break
        
        # Look for price - Facebook typically shows prices with $ symbol
        price = None
        price_text = item.get_text()
        if "$" in price_text:
            # Extract price pattern
            import re
            price_match = re.search(r'\$[\d,]+(?:\.\d{2})?', price_text)
            if price_match:
                price = price_match.group()

        # Facebook Marketplace locations are typically shown but harder to parse
        # May need to be extracted from structured data or API
        neighborhood = None

        # Build full URL
        url = urljoin(base_url, href) if not href.startswith("http") else href
        # Clean up URL parameters
        url = url.split("?")[0]

        if not title:
            logger.warning("Listing missing title", extra={"post_id": post_id})
            title = "Facebook Marketplace Listing"

        listings.append(
            Listing(
                post_id=post_id,
                title=title,
                price=price,
                neighborhood=neighborhood,
                url=url,
            )
        )

    # If no listings found with the above method, log a warning
    if not listings:
        logger.warning(
            "No Facebook Marketplace listings parsed. "
            "Facebook uses dynamic rendering - consider using Selenium or the Graph API for better results."
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
    parser = argparse.ArgumentParser(description="Facebook Marketplace rental scraper.")
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
