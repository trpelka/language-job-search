import csv
import email
import imaplib
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import quote

import pandas as pd
import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent

DATABASE = BASE_DIR / "local_jobs.db"
CSV_FILE = BASE_DIR / "jobs.csv"

SEARCH_TERMS = [
    "translator",
    "localization",
    "transcreation",
    "copywriter",
    "content writer",
    "technical writer",
    "language analyst",
    "linguist",
    "multilingual",
    "AI language",
    "research analyst",
    "OSINT",
    "proofreader",
    "editor",
]

LOCATION = "Poland"
RESULTS_WANTED = 20
HOURS_OLD = 72

COUNTRY_INDEED = "poland"

REQUEST_TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/138.0 Safari/537.36"
    )
}


def configure_geocoder():
    geocoder = MagicMock()
    ip_result = MagicMock()
    ip_result.country = "usa"
    geocoder.ip.return_value = ip_result
    sys.modules["geocoder"] = geocoder


def initialize_database():
    connection = sqlite3.connect(DATABASE)

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_jobs (
            job_url TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            location TEXT,
            source TEXT,
            description TEXT,
            found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    connection.commit()

    return connection


def job_seen(connection, job_url):
    return (
        connection.execute(
            "SELECT 1 FROM seen_jobs WHERE job_url = ?",
            (job_url,),
        ).fetchone()
        is not None
    )


def save_job(connection, job):
    connection.execute(
        """
        INSERT OR IGNORE INTO seen_jobs
        (
            job_url,
            title,
            company,
            location,
            source,
            description
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            job["job_url"],
            job["title"],
            job["company"],
            job["location"],
            job["source"],
            job["description"],
        ),
    )

    connection.commit()


def make_job(
    title="",
    company="",
    location="",
    source="",
    url="",
    description="",
):
    return {
        "title": str(title).strip(),
        "company": str(company).strip(),
        "location": str(location).strip(),
        "source": str(source).strip(),
        "job_url": str(url).strip(),
        "description": str(description).strip(),
    }


def scrape_jobspy_site(site):
    from jobspy import scrape_jobs

    results = []

    for term in SEARCH_TERMS:
        print(f"[{site}] searching: {term}")

        try:
            jobs: pd.DataFrame = scrape_jobs(
                site_name=site,
                search_term=term,
                location=LOCATION,
                results_wanted=RESULTS_WANTED,
                hours_old=HOURS_OLD,
                country_indeed=COUNTRY_INDEED,
            )

        except Exception as error:
            print(f"[{site}] failed for '{term}': {error}")
            continue

        if jobs is None or jobs.empty:
            continue

        for _, row in jobs.iterrows():
            url = str(row.get("job_url", "")).strip()

            if not url:
                continue

            results.append(
                make_job(
                    title=row.get("title", ""),
                    company=row.get("company", ""),
                    location=row.get("location", ""),
                    source=site,
                    url=url,
                    description=row.get("description", ""),
                )
            )

    return results


def fetch_isitfair(source):
    results = []

    for term in SEARCH_TERMS:
        print(f"[{source}] searching: {term}")

        try:
            response = requests.get(
                "https://isitfair.pl/api/v1/offers/search",
                params={
                    "offer_status": "active",
                    "offer_source": source,
                    "search": term,
                    "page": 1,
                },
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()
            data = response.json()

        except Exception as error:
            print(f"[{source}] failed for '{term}': {error}")
            continue

        offers = data

        if isinstance(data, dict):
            offers = data.get("offers", data.get("results", []))

        if not isinstance(offers, list):
            continue

        for offer in offers:
            if not isinstance(offer, dict):
                continue

            url = (
                offer.get("url")
                or offer.get("link")
                or offer.get("job_url")
                or ""
            )

            title = offer.get("title", "")
            company = offer.get("company", "")
            location = offer.get("location", "")
            description = (
                offer.get("description")
                or offer.get("snippet")
                or ""
            )

            if not url or not title:
                continue

            results.append(
                make_job(
                    title=title,
                    company=company,
                    location=location,
                    source=source,
                    url=url,
                    description=description,
                )
            )

    return results


def fetch_jooble():
    api_key = os.getenv("JOOBLE_API_KEY", "").strip()

    if not api_key:
        print("[jooble] JOOBLE_API_KEY not configured - skipped")
        return []

    results = []

    endpoint = f"https://pl.jooble.org/api/{api_key}"

    for term in SEARCH_TERMS:
        print(f"[jooble] searching: {term}")

        try:
            response = requests.post(
                endpoint,
                json={
                    "keywords": term,
                    "location": LOCATION,
                    "page": 1,
                    "ResultOnPage": RESULTS_WANTED,
                    "companysearch": False,
                },
                headers={
                    **HEADERS,
                    "Content-Type": "application/json",
                },
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()
            data = response.json()

        except Exception as error:
            print(f"[jooble] failed for '{term}': {error}")
            continue

        for offer in data.get("jobs", []):
            url = offer.get("link", "")

            if not url:
                continue

            results.append(
                make_job(
                    title=offer.get("title", ""),
                    company=offer.get("company", ""),
                    location=offer.get("location", ""),
                    source="jooble",
                    url=url,
                    description=offer.get("snippet", ""),
                )
            )

    return results


def fetch_theprotocol():
    results = []

    for term in SEARCH_TERMS:
        print(f"[theprotocol.it] searching: {term}")

        url = (
            "https://theprotocol.it/praca?kw="
            + quote(term)
        )

        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

        except Exception as error:
            print(
                f"[theprotocol.it] "
                f"failed for '{term}': {error}"
            )
            continue

        links = soup.find_all("a", href=True)

        seen_urls = set()

        for link in links:
            href = link.get("href", "")

            if ",oferta," not in href:
                continue

            if href.startswith("/"):
                job_url = "https://theprotocol.it" + href
            elif href.startswith("http"):
                job_url = href
            else:
                continue

            if job_url in seen_urls:
                continue

            seen_urls.add(job_url)

            title = link.get_text(
                " ",
                strip=True,
            )

            if not title:
                continue

            parent = link.parent

            description = ""

            if parent:
                description = parent.get_text(
                    " ",
                    strip=True,
                )

            results.append(
                make_job(
                    title=title,
                    company="",
                    location="",
                    source="theprotocol.it",
                    url=job_url,
                    description=description,
                )
            )

    return results


def fetch_linkedin_email_jobs():
    email_user = os.getenv("EMAIL_USER", "").strip()
    email_password = os.getenv("EMAIL_PASSWORD", "").strip()

    if not email_user or not email_password:
        print(
            "[linkedin-email] "
            "EMAIL_USER/EMAIL_PASSWORD not configured - skipped"
        )
        return []

    results = []

    try:
        mailbox = imaplib.IMAP4_SSL("imap.gmail.com")

        mailbox.login(
            email_user,
            email_password,
        )

        mailbox.select("INBOX")

        status, data = mailbox.search(
            None,
            '(FROM "jobalerts-noreply@linkedin.com")',
        )

        if status != "OK":
            print("[linkedin-email] search failed")
            mailbox.logout()
            return []

        message_ids = data[0].split()

        for message_id in message_ids[-100:]:
            status, message_data = mailbox.fetch(
                message_id,
                "(RFC822)",
            )

            if status != "OK":
                continue

            raw_email = message_data[0][1]

            message = email.message_from_bytes(
                raw_email
            )

            html = ""

            if message.is_multipart():
                for part in message.walk():
                    content_type = part.get_content_type()

                    if content_type == "text/html":
                        payload = part.get_payload(
                            decode=True
                        )

                        if payload:
                            html = payload.decode(
                                "utf-8",
                                errors="ignore",
                            )

                        break

            else:
                payload = message.get_payload(
                    decode=True
                )

                if payload:
                    html = payload.decode(
                        "utf-8",
                        errors="ignore",
                    )

            if not html:
                continue

            soup = BeautifulSoup(
                html,
                "html.parser",
            )

            for link in soup.find_all(
                "a",
                href=True,
            ):
                href = link["href"]

                if "linkedin.com/jobs/" not in href:
                    continue

                title = link.get_text(
                    " ",
                    strip=True,
                )

                if not title:
                    continue

                results.append(
                    make_job(
                        title=title,
                        company="",
                        location="",
                        source="linkedin-email",
                        url=href,
                        description="",
                    )
                )

        mailbox.logout()

    except Exception as error:
        print(
            f"[linkedin-email] failed: {error}"
        )

    return results


def deduplicate_jobs(jobs):
    unique = {}
    seen_urls = set()

    for job in jobs:
        url = job["job_url"]

        if not url:
            continue

        normalized = re.sub(
            r"[?#].*$",
            "",
            url,
        )

        if normalized in seen_urls:
            continue

        seen_urls.add(normalized)
        job["job_url"] = normalized
        unique[normalized] = job

    return list(unique.values())


def write_csv(connection):
    rows = connection.execute(
        """
        SELECT
            title,
            company,
            location,
            source,
            job_url,
            description,
            found_at
        FROM seen_jobs
        ORDER BY found_at DESC
        """
    ).fetchall()

    fieldnames = [
        "title",
        "company",
        "location",
        "source",
        "job_url",
        "description",
        "found_at",
    ]

    with CSV_FILE.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)

        writer.writerow(fieldnames)

        writer.writerows(rows)

    print(
        f"CSV written: {CSV_FILE}"
    )

    print(
        f"Total stored jobs: {len(rows)}"
    )


def run():
    print("=" * 60)
    print("JOB SCRAPER")
    print("=" * 60)

    connection = initialize_database()

    all_jobs = []

    try:
        all_jobs.extend(
            scrape_jobspy_site("indeed")
        )

        all_jobs.extend(
            fetch_isitfair("justjoin.it")
        )

        all_jobs.extend(
            fetch_isitfair("pracuj.pl")
        )

        all_jobs.extend(
            fetch_isitfair("nofluffjobs.com")
        )

        all_jobs.extend(
            fetch_theprotocol()
        )

        all_jobs.extend(
            fetch_jooble()
        )

        all_jobs.extend(
            fetch_linkedin_email_jobs()
        )

        all_jobs = deduplicate_jobs(all_jobs)

        print(
            f"\nCollected {len(all_jobs)} unique results."
        )

        new_jobs = 0

        for job in all_jobs:
            if job_seen(
                connection,
                job["job_url"],
            ):
                continue

            save_job(
                connection,
                job,
            )

            new_jobs += 1

        write_csv(connection)

        print(
            f"\nNew jobs added: {new_jobs}"
        )

    finally:
        connection.close()

    print("\nDONE")


if __name__ == "__main__":
    configure_geocoder()
    run()
