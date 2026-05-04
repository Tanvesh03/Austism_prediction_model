"""
Booking.com Hotel Scraper
Scrapes hotel listings: name, price, rating, location, review count, and availability dates.
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import random
import csv
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, fields
from typing import Optional


@dataclass
class HotelListing:
    name: str
    location: str
    price_per_night: Optional[str]
    currency: Optional[str]
    rating: Optional[str]
    review_count: Optional[str]
    review_label: Optional[str]
    checkin_date: str
    checkout_date: str
    url: Optional[str]


class BookingScraper:
    BASE_URL = "https://www.booking.com/searchresults.html"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://www.booking.com/",
    }

    def __init__(self, delay_range=(2, 5)):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.delay_range = delay_range

    def _build_url(self, destination: str, checkin: str, checkout: str, adults: int, offset: int) -> str:
        params = {
            "ss": destination,
            "checkin": checkin,
            "checkout": checkout,
            "group_adults": adults,
            "no_rooms": 1,
            "offset": offset,
            "lang": "en-us",
            "selected_currency": "USD",
        }
        req = requests.Request("GET", self.BASE_URL, params=params)
        return req.prepare().url

    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except requests.RequestException as e:
            print(f"[ERROR] Failed to fetch {url}: {e}")
            return None

    def _parse_hotels(self, soup: BeautifulSoup, checkin: str, checkout: str) -> list[HotelListing]:
        hotels = []

        # Booking.com uses data-testid attributes for their search result cards
        cards = soup.find_all("div", {"data-testid": "property-card"})

        for card in cards:
            # Name
            name_tag = card.find("div", {"data-testid": "title"})
            name = name_tag.get_text(strip=True) if name_tag else "N/A"

            # Location / address
            loc_tag = card.find("span", {"data-testid": "address"})
            location = loc_tag.get_text(strip=True) if loc_tag else "N/A"

            # Price
            price_tag = card.find("span", {"data-testid": "price-and-discounted-price"})
            if not price_tag:
                price_tag = card.find("div", class_=lambda c: c and "price" in c.lower())
            raw_price = price_tag.get_text(strip=True) if price_tag else None
            price, currency = self._parse_price(raw_price)

            # Rating score
            rating_tag = card.find("div", {"data-testid": "review-score"})
            rating, review_label, review_count = None, None, None
            if rating_tag:
                score_tag = rating_tag.find("div", class_=lambda c: c and "score" in c.lower())
                if not score_tag:
                    # fallback: first standalone number
                    score_tag = rating_tag.find("div")
                rating = score_tag.get_text(strip=True) if score_tag else None

                label_tag = rating_tag.find("div", class_=lambda c: c and ("label" in c.lower() or "word" in c.lower()))
                review_label = label_tag.get_text(strip=True) if label_tag else None

                count_tag = rating_tag.find("div", class_=lambda c: c and "count" in c.lower())
                review_count = count_tag.get_text(strip=True) if count_tag else None

            # URL
            link_tag = card.find("a", {"data-testid": "property-card-desktop-single-image"})
            if not link_tag:
                link_tag = card.find("a", href=True)
            hotel_url = link_tag["href"] if link_tag and link_tag.get("href") else None
            if hotel_url and hotel_url.startswith("/"):
                hotel_url = "https://www.booking.com" + hotel_url

            hotels.append(HotelListing(
                name=name,
                location=location,
                price_per_night=price,
                currency=currency,
                rating=rating,
                review_count=review_count,
                review_label=review_label,
                checkin_date=checkin,
                checkout_date=checkout,
                url=hotel_url,
            ))

        return hotels

    @staticmethod
    def _parse_price(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        if not raw:
            return None, None
        # Strip common currency symbols and split
        for symbol, code in [("$", "USD"), ("€", "EUR"), ("£", "GBP"), ("₹", "INR")]:
            if symbol in raw:
                amount = raw.replace(symbol, "").replace(",", "").strip()
                # Keep only numeric + decimal part
                numeric = "".join(c for c in amount if c.isdigit() or c == ".")
                return numeric or amount, code
        return raw, None

    def scrape(
        self,
        destination: str,
        checkin: Optional[str] = None,
        checkout: Optional[str] = None,
        adults: int = 2,
        max_pages: int = 3,
    ) -> list[HotelListing]:
        """
        Scrape hotel listings from Booking.com.

        Args:
            destination: City or location string (e.g. "Paris, France")
            checkin:     Check-in date in YYYY-MM-DD format (defaults to tomorrow)
            checkout:    Check-out date in YYYY-MM-DD format (defaults to checkin + 2 nights)
            adults:      Number of adult guests
            max_pages:   Maximum search result pages to scrape

        Returns:
            List of HotelListing dataclass instances
        """
        today = datetime.today()
        if not checkin:
            checkin = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        if not checkout:
            checkout = (datetime.strptime(checkin, "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d")

        print(f"Scraping Booking.com: destination='{destination}' | {checkin} → {checkout} | {adults} adults")

        all_hotels: list[HotelListing] = []

        for page in range(max_pages):
            offset = page * 25
            url = self._build_url(destination, checkin, checkout, adults, offset)
            print(f"  Page {page + 1}: {url}")

            soup = self._fetch_page(url)
            if not soup:
                break

            hotels = self._parse_hotels(soup, checkin, checkout)
            if not hotels:
                print(f"  No listings found on page {page + 1}. Stopping.")
                break

            all_hotels.extend(hotels)
            print(f"  Found {len(hotels)} listings (total: {len(all_hotels)})")

            if page < max_pages - 1:
                delay = random.uniform(*self.delay_range)
                print(f"  Waiting {delay:.1f}s before next page...")
                time.sleep(delay)

        return all_hotels

    def save_to_csv(self, hotels: list[HotelListing], filepath: str) -> None:
        if not hotels:
            print("No data to save.")
            return
        fieldnames = [f.name for f in fields(HotelListing)]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(asdict(h) for h in hotels)
        print(f"Saved {len(hotels)} records to {filepath}")

    def save_to_json(self, hotels: list[HotelListing], filepath: str) -> None:
        if not hotels:
            print("No data to save.")
            return
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([asdict(h) for h in hotels], f, indent=2, ensure_ascii=False)
        print(f"Saved {len(hotels)} records to {filepath}")


if __name__ == "__main__":
    scraper = BookingScraper(delay_range=(2, 4))

    hotels = scraper.scrape(
        destination="New York, USA",
        checkin="2026-06-01",
        checkout="2026-06-03",
        adults=2,
        max_pages=2,
    )

    if hotels:
        scraper.save_to_csv(hotels, "booking_results.csv")
        scraper.save_to_json(hotels, "booking_results.json")

        print("\n--- Sample Results ---")
        for h in hotels[:5]:
            print(f"  {h.name} | {h.location} | ${h.price_per_night} {h.currency} | Rating: {h.rating}")
    else:
        print("No hotels scraped. Booking.com may be blocking the request.")
        print("Consider using a headless browser (Playwright/Selenium) for more reliable scraping.")
