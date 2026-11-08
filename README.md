# language-job-search

Multilingual job search across Polish job boards and international aggregators, with SQLite de-duplication and a CSV export that updates itself twice a day.

Built for roles where language skills are the point: translation, localization, copywriting, technical writing, OSINT research, KYC / AML / financial-crime analysis.

## What it does

The script runs nine collectors, merges their results and keeps only jobs it has never seen before:

| Source | How it is queried |
| --- | --- |
| JobSpy | Indeed, LinkedIn (Glassdoor optional) |
| Pracuj.pl | public search pages |
| Just Join IT | public search pages |
| No Fluff Jobs | public search pages |
| RocketJobs | public search pages |
| Bulldogjob | public search pages |
| Jooble | public search pages |
| theProtocol | public search pages |
| Search discovery | Google results limited to the job-board domains above |

Every run:

- removes tracking parameters (`utm_*`, `gclid`, `fbclid`, …) and fragments before de-duplicating
- retries transient HTTP failures with exponential backoff
- keeps each collector independent, so one broken board does not stop the run
- respects a wall-clock budget so a slow board cannot hang the whole job
- writes a short Markdown report of what happened

Each run writes:

- `jobs.csv` — the last 7 days of jobs, newest first (UTF-8 BOM, opens cleanly in Excel)
- `local_jobs.db` — full de-duplication database; kept on the `data` branch, not in `main`
- `reports/latest.md` — summary for the latest run (git-ignored, uploaded as an artifact)

Duplicate detection is by normalized `job_url`, so re-running the script never inflates the CSV. The CSV is pruned to `CSV_RETENTION_DAYS` (default `7`) on every run; the database keeps the full history needed for de-duplication.

## Quick start

```bash
git clone https://github.com/trpelka/language-job-search.git
cd language-job-search
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python job_search_pl.py
```

Python 3.12 is what CI uses. `python-jobspy` occasionally needs a recent `pandas`, so install into a fresh virtualenv if you hit version conflicts.

### Command line

```bash
python job_search_pl.py --dry-run                 # collect and report, change nothing
python job_search_pl.py --sources pracuj,jooble   # run only selected collectors
python job_search_pl.py --limit 10                # use only the first 10 search terms
python job_search_pl.py --max-runtime 20          # hard stop after 20 minutes
```

Source keys: `jobspy`, `pracuj`, `justjoin`, `nofluffjobs`, `rocketjobs`, `bulldogjob`, `jooble`, `theprotocol`, `search`.

## Configuration

Search terms live at the top of `job_search_pl.py`:

```python
SEARCH_TERMS = [
    "translator",
    "localization",
    "OSINT analyst remote",
    "KYC analyst remote",
    "AML analyst remote",
    # ...
]
```

The list is extended automatically with `"<language> translator"` for every language in `LANGUAGES`. Add or remove terms freely. Each term is sent to every collector, so a smaller list means a faster run and fewer chances of being rate-limited.

Runtime settings can be set through the environment:

| Variable | Default | Purpose |
| --- | --- | --- |
| `LOCATION` | `Poland` | JobSpy search location |
| `MAX_RUNTIME_MIN` | `45` | Hard stop for the whole run, in minutes |
| `RESULTS_WANTED` | `50` | Results per JobSpy query |
| `HOURS_OLD` | `168` | JobSpy lookback window, in hours |
| `CSV_RETENTION_DAYS` | `7` | Days of jobs written to the committed CSV |
| `DESCRIPTION_LIMIT` | `4000` | Maximum stored description length |
| `JOBSPY_SITES` | `indeed,linkedin` | Comma-separated JobSpy boards |
| `JOBSPY_PROXIES` | empty | `user:pass@host:port,...` for blocked boards |

Set them in the shell (`$env:MAX_RUNTIME_MIN="20"` on Windows) or in the workflow `env:` block.

## Output

`jobs.csv` columns:

```text
title, company, location, source, job_url, description, found_at
```

The SQLite table `seen_jobs` stores the same fields plus `job_url` as the primary key. To start fresh, delete `local_jobs.db` locally or delete the `data` branch — the next run recreates an empty database.

`reports/latest.md` contains the run mode, new-job count, a per-source table and up to 25 new listings. It is printed into the GitHub Actions step summary on every run.

## Data and storage

Two files are deliberately separated:

| Data | Where | Size (typical) | Why |
| --- | --- | --- | --- |
| `jobs.csv` | `main`, rolling 7 days | ~1.3 MB | Humans browse and diff it; small enough to commit twice a day |
| `local_jobs.db` | `data` branch, single rolling commit | ~11 MB | Full de-duplication history without growing `main` |

The `data` branch is rewritten with `git push --force` on every run, so it always contains exactly one commit and one database file. Its storage footprint is therefore the size of the current database, not its history.

Why not Actions cache? The cache is convenient but limited to **10 GB per repository**, entries are evicted after **7 days without access**, and there is no API to seed it. The rolling `data` branch has no such eviction, survives pauses in the schedule, and is inspectable in the repository.

For reference, on GitHub Free:

- **Actions minutes and storage are free for public repositories** (2,000 minutes/month and 500 MB storage are the private-repo allowances).
- **Actions cache:** 10 GB per repository, entries expire after 7 days unused.
- **Artifacts:** 90-day default retention; here only the tiny Markdown report is uploaded.
- **Repository:** GitHub recommends staying under 1 GB; files over 100 MB trigger a warning and pushes over 2 GB are blocked.

The old blobs already in `main` history are not reclaimed by deleting the file now — that would require a history rewrite, which is not done here.

## Automation

`.github/workflows/run.yml` runs the search twice a day (`08:00` and `20:00` UTC). It restores `local_jobs.db` from the `data` branch, commits the rolling 7-day `jobs.csv` to `main`, force-pushes the updated database back to `data`, writes a run summary, uploads `reports/latest.md` as an artifact and can be triggered manually from the **Actions** tab.

No secrets are required; the workflow uses the default `GITHUB_TOKEN` with `contents: write`.

`ci.yml` runs linting and the test suite on every push and pull request. Dependabot keeps Python and GitHub Actions dependencies up to date.

## Development

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

The tests cover URL normalization, normalization/de-duplication, description truncation, 7-day CSV retention, CLI defaults and collector registry integrity. They do not touch the network.

## Limitations

- The Polish boards are scraped from public HTML, so a site redesign can break a collector. Each collector fails independently and the rest of the run continues.
- JobSpy sources (especially LinkedIn and Glassdoor) rate-limit datacenter IPs such as GitHub Actions runners. Local runs usually return more results; proxies help.
- Descriptions are only as complete as the page exposes; some boards return titles without a full description.
- No salary normalization or relevance ranking yet — the output is intentionally a raw, de-duplicated feed.
- `local_jobs.db` grows with every new URL. It is kept out of `main`, but the `data` branch will grow to tens of megabytes over years; prune `seen_jobs` if that ever matters.
