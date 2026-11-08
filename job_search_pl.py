import argparse
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import (
    parse_qsl,
    quote_plus,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

import pandas as pd
import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DATABASE = BASE_DIR / "local_jobs.db"
CSV_FILE = BASE_DIR / "jobs.csv"

LOCATION = os.getenv("LOCATION", "Poland")

SEARCH_TERMS = [
    # --- translation / language ---
    "translator",
    "localization",
    "localisation",
    "copywriter",
    "content writer",
    "content specialist",
    "proofreader",
    "editor",
    "linguist",
    "language specialist",
    "transcreation",
    "technical writer",
    "English translator",
    "French translator",
    "German translator",
    "Spanish translator",
    "Italian translator",
    "Portuguese translator",
    "Dutch translator",
    "Romanian translator",

    # --- OSINT / research ---
    "OSINT analyst remote",
    "OSINT researcher remote",
    "due diligence",
    "due diligence research remote",
    "open source intelligence analyst",
    "multilingual researcher remote",
    "investigative researcher remote",
    "threat intelligence analyst remote",

    # --- KYC ---
    "KYC analyst remote",
    "KYC specialist remote",
    "KYC onboarding analyst remote",
    "KYC researcher",
    "client due diligence analyst",
    "customer due diligence remote",
    "enhanced due diligence analyst",
    "EDD analyst remote",
    "multilingual KYC analyst",
    "German speaking KYC",
    "Polish speaking KYC",

    # --- AML / financial crime ---
    "AML analyst remote",
    "AML specialist remote",
    "AML compliance analyst",
    "AML investigator remote",
    "financial crime analyst remote",
    "financial crime investigator",
    "sanctions screening analyst",
    "sanctions analyst remote",
    "adverse media analyst",
    "transaction monitoring analyst remote",
    "compliance analyst remote",
    "fraud analyst remote",
]

LANGUAGES = [
    "English",
    "French",
    "German",
    "Spanish",
    "Italian",
    "Portuguese",
    "Dutch",
    "Romanian",
    "Swedish",
    "Norwegian",
    "Danish",
    "Russian",
    "Ukrainian",
    "Polish",
]

# One "translator" query per language, without duplicating the explicit terms above.
SEARCH_TERMS = list(
    dict.fromkeys(SEARCH_TERMS + [f"{language} translator" for language in LANGUAGES])
)

REQUEST_TIMEOUT = 20
MAX_RUNTIME_MIN = int(os.getenv("MAX_RUNTIME_MIN", "45"))
REQUEST_DELAY = (0.4, 1.2)
DESCRIPTION_LIMIT = int(os.getenv("DESCRIPTION_LIMIT", "4000"))
RESULTS_WANTED = int(os.getenv("RESULTS_WANTED", "50"))
HOURS_OLD = int(os.getenv("HOURS_OLD", "168"))
JOBSPY_SITES = [
    site.strip()
    for site in os.getenv("JOBSPY_SITES", "indeed,linkedin").split(",")
    if site.strip()
]
PROXIES = [
    proxy.strip()
    for proxy in os.getenv("JOBSPY_PROXIES", "").split(",")
    if proxy.strip()
] or None
TRACKING_PARAMS = {
    "gclid",
    "fbclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
    "source",
    "trk",
}
REPORT_FILE = BASE_DIR / "reports" / "latest.md"
RUN_STARTED = time.monotonic()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
}


# ============================================================
# DATABASE
# ============================================================

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


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    value = str(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def absolute_url(url, base_url):
    if not url:
        return ""

    return urljoin(base_url, url)


def normalize_url(url):
    """Lower-case the host, drop tracking parameters and fragments, strip a trailing slash."""
    if not url:
        return ""

    parsed = urlparse(url)

    if not parsed.scheme or not parsed.netloc:
        return url.strip()

    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in TRACKING_PARAMS
            and not key.lower().startswith("utm_")
        ]
    )
    path = parsed.path.rstrip("/") or "/"

    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            query,
            "",
        )
    )


def out_of_time():
    return (time.monotonic() - RUN_STARTED) / 60 >= MAX_RUNTIME_MIN


def configure_geocoder():
    """Stop JobSpy from doing an IP geolocation lookup, which fails or is rate-limited on CI."""
    geocoder = MagicMock()
    ip_result = MagicMock()
    ip_result.country = "poland"
    geocoder.ip.return_value = ip_result
    sys.modules["geocoder"] = geocoder


def make_job(title, company, location, source, url, description=""):
    return {
        "title": clean_text(title),
        "company": clean_text(company),
        "location": clean_text(location),
        "source": clean_text(source),
        "job_url": clean_text(url),
        "description": clean_text(description),
    }


def request_page(url, params=None, attempts=3):
    """GET a page with politeness delay, a time budget and retries for transient failures."""
    if out_of_time():
        print("  Time budget exhausted, skipping request")
        return None

    time.sleep(random.uniform(*REQUEST_DELAY))

    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(f"HTTP {response.status_code}")

            if response.status_code >= 400:
                print(f"  Request rejected: HTTP {response.status_code}")
                return None

            return response.text

        except Exception as error:
            if attempt == attempts:
                print(f"  Request failed after {attempts} attempts: {error}")
                return None

            backoff = 2**attempt + random.uniform(0, 1)
            print(f"  Request failed ({error}); retrying in {backoff:.1f}s")
            time.sleep(backoff)

    return None


# ============================================================
# JOBSPY COLLECTOR
#
# Uses JobSpy where supported.
# A failure here does NOT stop the other collectors.
# ============================================================

def collect_jobspy():
    jobs = []

    try:
        from jobspy import scrape_jobs
    except Exception as error:
        print(f"JobSpy unavailable: {error}")
        return jobs

    print("\n========== JOBSPY ==========")

    for term in SEARCH_TERMS:
        if out_of_time():
            print("  Time budget exhausted, stopping JobSpy")
            break

        print(f"JobSpy: {term}")

        try:
            data = scrape_jobs(
                site_name=JOBSPY_SITES,
                search_term=term,
                location=LOCATION,
                results_wanted=RESULTS_WANTED,
                hours_old=HOURS_OLD,
                country_indeed="poland",
                proxies=PROXIES,
            )

            if data is None or data.empty:
                continue

            for _, row in data.iterrows():
                jobs.append(
                    make_job(
                        row.get("title", ""),
                        row.get("company", ""),
                        row.get("location", ""),
                        row.get("site", ""),
                        row.get("job_url", ""),
                        row.get("description", ""),
                    )
                )

            print(f"  {len(data)} results")

        except Exception as error:
            print(f"  Failed: {error}")

    return jobs


# ============================================================
# PRACUJ.PL
# ============================================================

def collect_pracuj():
    jobs = []

    print("\n========== PRACUJ.PL ==========")

    base_url = "https://www.pracuj.pl"

    for term in SEARCH_TERMS:
        url = f"{base_url}/praca/{quote_plus(term)};kw"

        html = request_page(url)

        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")

            if "/oferta/" not in href:
                continue

            title = clean_text(link.get_text(" ", strip=True))

            if not title:
                continue

            jobs.append(
                make_job(
                    title,
                    "",
                    LOCATION,
                    "pracuj.pl",
                    absolute_url(href, base_url),
                )
            )

    return jobs


# ============================================================
# JUST JOIN IT
# ============================================================

def collect_justjoinit():
    jobs = []

    print("\n========== JUST JOIN IT ==========")

    for term in SEARCH_TERMS:
        url = (
            "https://justjoin.it/job-offers/all-locations/"
            + quote_plus(term)
        )

        html = request_page(url)

        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")

            if "/job-offer/" not in href:
                continue

            title = clean_text(link.get_text(" ", strip=True))

            if not title:
                continue

            jobs.append(
                make_job(
                    title,
                    "",
                    LOCATION,
                    "justjoin.it",
                    absolute_url(href, "https://justjoin.it"),
                )
            )

    return jobs


# ============================================================
# NO FLUFF JOBS
# ============================================================

def collect_nofluffjobs():
    jobs = []

    print("\n========== NO FLUFF JOBS ==========")

    base_url = "https://nofluffjobs.com"

    for term in SEARCH_TERMS:
        url = (
            f"{base_url}/pl/{quote_plus(term)}"
        )

        html = request_page(url)

        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")

            if "/pl/job/" not in href:
                continue

            title = clean_text(link.get_text(" ", strip=True))

            if not title:
                continue

            jobs.append(
                make_job(
                    title,
                    "",
                    LOCATION,
                    "nofluffjobs",
                    absolute_url(href, base_url),
                )
            )

    return jobs


# ============================================================
# ROCKETJOBS
# ============================================================

def collect_rocketjobs():
    jobs = []

    print("\n========== ROCKETJOBS ==========")

    base_url = "https://rocketjobs.pl"

    for term in SEARCH_TERMS:
        url = f"{base_url}/?query={quote_plus(term)}"

        html = request_page(url)

        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")

            if "/oferta/" not in href:
                continue

            title = clean_text(link.get_text(" ", strip=True))

            if not title:
                continue

            jobs.append(
                make_job(
                    title,
                    "",
                    LOCATION,
                    "rocketjobs",
                    absolute_url(href, base_url),
                )
            )

    return jobs


# ============================================================
# BULLDOGJOB
# ============================================================

def collect_bulldogjob():
    jobs = []

    print("\n========== BULLDOGJOB ==========")

    base_url = "https://bulldogjob.pl"

    for term in SEARCH_TERMS:
        url = f"{base_url}/it-jobs?search={quote_plus(term)}"

        html = request_page(url)

        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")

            if "/companies/" not in href and "/jobs/" not in href:
                continue

            title = clean_text(link.get_text(" ", strip=True))

            if not title:
                continue

            jobs.append(
                make_job(
                    title,
                    "",
                    LOCATION,
                    "bulldogjob",
                    absolute_url(href, base_url),
                )
            )

    return jobs


# ============================================================
# JOOBLE
# ============================================================

def collect_jooble():
    jobs = []

    print("\n========== JOOBLE ==========")

    base_url = "https://pl.jooble.org"

    for term in SEARCH_TERMS:
        url = f"{base_url}/szukaj-prace/{quote_plus(term)}"

        html = request_page(url)

        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")

            if not href:
                continue

            title = clean_text(link.get_text(" ", strip=True))

            if len(title) < 5:
                continue

            if term.lower() not in title.lower():
                continue

            jobs.append(
                make_job(
                    title,
                    "",
                    LOCATION,
                    "jooble",
                    absolute_url(href, base_url),
                )
            )

    return jobs


# ============================================================
# THE PROTOCOL
# ============================================================

def collect_theprotocol():
    jobs = []

    print("\n========== THE PROTOCOL ==========")

    base_url = "https://theprotocol.it"

    for term in SEARCH_TERMS:
        url = f"{base_url}/szukaj?query={quote_plus(term)}"

        html = request_page(url)

        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")

            if "/oferta/" not in href:
                continue

            title = clean_text(link.get_text(" ", strip=True))

            if not title:
                continue

            jobs.append(
                make_job(
                    title,
                    "",
                    LOCATION,
                    "theprotocol",
                    absolute_url(href, base_url),
                )
            )

    return jobs


# ============================================================
# GENERIC GOOGLE SEARCH COLLECTOR
#
# This is intentionally limited to job-board domains.
# It can discover pages even when a board has no direct
# collector above.
# ============================================================

def collect_google_results():
    jobs = []

    print("\n========== SEARCH DISCOVERY ==========")

    domains = [
        "pracuj.pl",
        "justjoin.it",
        "nofluffjobs.com",
        "rocketjobs.pl",
        "bulldogjob.pl",
        "jooble.org",
        "theprotocol.it",
    ]

    for term in SEARCH_TERMS[:10]:
        query = (
            f'"{term}" '
            f'Poland '
            f'({" OR ".join(f"site:{domain}" for domain in domains)})'
        )

        url = (
            "https://www.google.com/search?q="
            + quote_plus(query)
        )

        html = request_page(url)

        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        for result in soup.select("div.MjjYud"):
            link = result.find("a", href=True)

            if not link:
                continue

            href = link.get("href", "")

            title_tag = result.find(["h3"])

            if not title_tag:
                continue

            title = clean_text(title_tag.get_text())

            if not title:
                continue

            if href.startswith("/url?q="):
                href = href.split("/url?q=", 1)[1].split("&", 1)[0]

            jobs.append(
                make_job(
                    title,
                    "",
                    LOCATION,
                    "search-discovery",
                    href,
                )
            )

    return jobs


# ============================================================
# NORMALIZATION / DEDUPLICATION
# ============================================================

def normalize_jobs(jobs):
    if not jobs:
        return pd.DataFrame(
            columns=[
                "title",
                "company",
                "location",
                "source",
                "job_url",
                "description",
            ]
        )

    data = pd.DataFrame(jobs)

    columns = [
        "title",
        "company",
        "location",
        "source",
        "job_url",
        "description",
    ]

    for column in columns:
        if column not in data.columns:
            data[column] = ""

    data = data[columns]

    for column in columns:
        data[column] = data[column].fillna("").astype(str).str.strip()

    data["job_url"] = data["job_url"].map(normalize_url)
    data["description"] = data["description"].str.slice(0, DESCRIPTION_LIMIT)

    data = data[data["job_url"] != ""]

    data = data.drop_duplicates(
        subset=["job_url"],
        keep="first",
    )

    return data


# ============================================================
# DATABASE + CSV
# ============================================================

def write_report(new_jobs, total, new_by_source, dry_run=False):
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Language job search - latest run",
        "",
        f"- Run: {timestamp}",
        f"- Mode: {'dry run (nothing saved)' if dry_run else 'live'}",
        f"- New jobs: {len(new_jobs)}",
        f"- Total in database: {total}",
        "",
    ]

    if new_by_source:
        lines += ["## New jobs by source", "", "| Source | New |", "| --- | --- |"]
        for source, count in sorted(
            new_by_source.items(), key=lambda item: (-item[1], item[0])
        ):
            lines.append(f"| {source or 'unknown'} | {count} |")
        lines.append("")

    if new_jobs:
        lines += ["## Newest jobs", ""]
        for job in new_jobs[:25]:
            company = job.get("company") or "unknown company"
            lines.append(
                f"- **{job.get('title', '')}** - {company} "
                f"({job.get('source', '')}) - {job.get('job_url', '')}"
            )
        lines.append("")

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report:           {REPORT_FILE}")


def save_jobs(jobs, dry_run=False):
    new_by_source = {}
    new_jobs = []

    if dry_run:
        for _, row in jobs.iterrows():
            job = row.to_dict()
            new_jobs.append(job)
            source = job["source"]
            new_by_source[source] = new_by_source.get(source, 0) + 1

        print("\n==========================================")
        print("DRY RUN - database and CSV were not changed")
        print(f"Jobs this run:    {len(jobs)}")
        print("==========================================")

        write_report(new_jobs, len(jobs), new_by_source, dry_run=True)
        return {"new": len(new_jobs), "total": len(jobs)}

    connection = initialize_database()

    try:
        for _, row in jobs.iterrows():
            cursor = connection.execute(
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
                    row["job_url"],
                    row["title"],
                    row["company"],
                    row["location"],
                    row["source"],
                    row["description"],
                ),
            )

            if cursor.rowcount:
                job = row.to_dict()
                new_jobs.append(job)
                source = job["source"]
                new_by_source[source] = new_by_source.get(source, 0) + 1

        connection.commit()

        all_jobs = pd.read_sql_query(
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
            """,
            connection,
        )

        all_jobs.to_csv(
            CSV_FILE,
            index=False,
            encoding="utf-8-sig",
        )

        print("\n==========================================")
        print(f"Results this run: {len(jobs)}")
        print(f"New jobs:         {len(new_jobs)}")
        print(f"Total database:   {len(all_jobs)}")
        print(f"CSV:              {CSV_FILE}")
        print("==========================================")

        write_report(new_jobs, len(all_jobs), new_by_source)

        return {"new": len(new_jobs), "total": len(all_jobs)}

    finally:
        connection.close()


# ============================================================
# MAIN
# ============================================================

COLLECTORS = [
    ("jobspy", "JobSpy", collect_jobspy),
    ("pracuj", "Pracuj.pl", collect_pracuj),
    ("justjoin", "Just Join IT", collect_justjoinit),
    ("nofluffjobs", "No Fluff Jobs", collect_nofluffjobs),
    ("rocketjobs", "RocketJobs", collect_rocketjobs),
    ("bulldogjob", "Bulldogjob", collect_bulldogjob),
    ("jooble", "Jooble", collect_jooble),
    ("theprotocol", "theProtocol", collect_theprotocol),
    ("search", "Search discovery", collect_google_results),
]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Search Polish and international job boards for language-heavy roles."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="collect and report without changing the database or CSV",
    )
    parser.add_argument(
        "--sources",
        help="comma-separated subset of: " + ", ".join(key for key, _, _ in COLLECTORS),
    )
    parser.add_argument(
        "--max-runtime",
        type=int,
        help=f"hard stop in minutes (default {MAX_RUNTIME_MIN})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="maximum search terms per collector",
    )
    return parser.parse_args(argv)


def main(argv=None):
    global MAX_RUNTIME_MIN, SEARCH_TERMS

    args = parse_args(argv)

    if args.max_runtime:
        MAX_RUNTIME_MIN = args.max_runtime

    if args.limit:
        SEARCH_TERMS = SEARCH_TERMS[: args.limit]

    selected = None
    if args.sources:
        selected = {name.strip() for name in args.sources.split(",") if name.strip()}
        unknown = selected - {key for key, _, _ in COLLECTORS}
        if unknown:
            print(f"Unknown sources: {', '.join(sorted(unknown))}")
            return 2

    print("=" * 60)
    print("LANGUAGE JOB SEARCH")
    print("=" * 60)
    print(f"Location: {LOCATION}")
    print(f"Search terms: {len(SEARCH_TERMS)} | runtime cap: {MAX_RUNTIME_MIN} min")

    configure_geocoder()

    all_jobs = []

    for key, label, collector in COLLECTORS:
        if selected and key not in selected:
            continue

        if out_of_time():
            print("Time budget exhausted; skipping remaining collectors")
            break

        try:
            results = collector()

            print(f"{label}: {len(results)} results")

            all_jobs.extend(results)

        except Exception as error:
            print(f"{label} FAILED: {error}")

    jobs = normalize_jobs(all_jobs)

    save_jobs(jobs, dry_run=args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
