# language-job-search

Multilingual job search across Polish job boards and international aggregators, with SQLite de-duplication and a CSV export that updates itself twice a day.

Built for roles where language skills are the point: translation, localization, copywriting, technical writing, OSINT research, KYC / AML / financial-crime analysis.

## What it does

The script runs nine collectors, merges their results and keeps only jobs it has never seen before:

| Source | How it is queried |
| --- | --- |
| JobSpy | LinkedIn, Indeed, Glassdoor |
| Pracuj.pl | public search pages |
| Just Join IT | public search pages |
| No Fluff Jobs | public search pages |
| RocketJobs | public search pages |
| Bulldogjob | public search pages |
| Jooble | public search pages |
| theProtocol | public search pages |
| Search discovery | Google results limited to the job-board domains above |

Each run writes:

- `jobs.csv` — every job ever found, newest first (UTF-8 BOM, opens cleanly in Excel)
- `local_jobs.db` — SQLite database used for de-duplication

Duplicate detection is by `job_url`, so re-running the script never inflates the CSV.

## Quick start

```bash
git clone https://github.com/trpelka/language-job-search.git
cd language-job-search
pip install -r requirements.txt
python "job search pl.py"
```

Python 3.12 is what CI uses. `python-jobspy` occasionally needs a recent `pandas`, so install into a fresh virtualenv if you hit version conflicts.

## Configuration

Everything lives at the top of `job search pl.py`:

```python
LOCATION = "Poland"

SEARCH_TERMS = [
    "translator",
    "localization",
    "OSINT analyst remote",
    "KYC analyst remote",
    "AML analyst remote",
    # ...
]
```

Add or remove search terms freely. Each term is sent to every collector, so a smaller list means a faster run and fewer chances of being rate-limited.

## Output

`jobs.csv` columns:

```text
title, company, location, source, job_url, description, found_at
```

The SQLite table `seen_jobs` stores the same fields plus `job_url` as the primary key. To start fresh, delete both files — the next run recreates them.

## Automation

`.github/workflows/run.yml` runs the search twice a day (`08:00` and `20:00` UTC) and commits the updated CSV and database back to the repository. You can also trigger it manually from the **Actions** tab.

No secrets are required; the workflow uses the default `GITHUB_TOKEN` with `contents: write`.

## Limitations

- The Polish boards are scraped from public HTML, so a site redesign can break a collector. Each collector fails independently and the rest of the run continues.
- JobSpy sources (especially LinkedIn and Glassdoor) rate-limit datacenter IPs such as GitHub Actions runners. Local runs usually return more results.
- Descriptions are only as complete as the page exposes; some boards return titles without a full description.
- No salary normalization or relevance ranking yet — the output is intentionally a raw, de-duplicated feed.
