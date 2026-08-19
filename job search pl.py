import re
import sqlite3
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DATABASE = BASE_DIR / "local_jobs.db"
CSV_FILE = BASE_DIR / "jobs.csv"

LOCATION = "Poland"

SEARCH_TERMS = [
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

REQUEST_TIMEOUT = 20

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


def make_job(title, company, location, source, url, description=""):
    return {
        "title": clean_text(title),
        "company": clean_text(company),
        "location": clean_text(location),
        "source": clean_text(source),
        "job_url": clean_text(url),
        "description": clean_text(description),
    }


def request_page(url, params=None):
    try:
        response = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        return response.text

    except Exception as error:
        print(f"  Request failed: {error}")
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
        print(f"JobSpy: {term}")

        try:
            data = scrape_jobs(
                site_name=[
                    "linkedin",
                    "indeed",
                    "glassdoor",
                ],
                search_term=term,
                location=LOCATION,
                results_wanted=50,
                hours_old=168,
                country_indeed="poland",
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

    data = data[data["job_url"] != ""]

    data = data.drop_duplicates(
        subset=["job_url"],
        keep="first",
    )

    return data


# ============================================================
# DATABASE + CSV
# ============================================================

def save_jobs(jobs):
    connection = initialize_database()

    try:
        new_count = 0

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
                new_count += 1

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
        print(f"New jobs:         {new_count}")
        print(f"Total database:   {len(all_jobs)}")
        print(f"CSV:              {CSV_FILE}")
        print("==========================================")

    finally:
        connection.close()


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("LANGUAGE JOB SEARCH")
    print("=" * 60)

    collectors = [
        ("JobSpy", collect_jobspy),
        ("Pracuj.pl", collect_pracuj),
        ("Just Join IT", collect_justjoinit),
        ("No Fluff Jobs", collect_nofluffjobs),
        ("RocketJobs", collect_rocketjobs),
        ("Bulldogjob", collect_bulldogjob),
        ("Jooble", collect_jooble),
        ("theProtocol", collect_theprotocol),
        ("Search discovery", collect_google_results),
    ]

    all_jobs = []

    for name, collector in collectors:
        try:
            results = collector()

            print(f"{name}: {len(results)} results")

            all_jobs.extend(results)

        except Exception as error:
            print(f"{name} FAILED: {error}")

    jobs = normalize_jobs(all_jobs)

    save_jobs(jobs)


if __name__ == "__main__":
    main()
