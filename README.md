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

- `jobs.csv` — every job ever found, newest first (UTF-8 BOM, opens cleanly in Excel)
- `local_jobs.db` — SQLite database used for de-duplication
- `reports/latest.md` — summary for the latest run (git-ignored, uploaded as an artifact)

Duplicate detection is by normalized `job_url`, so re-running the script never inflates the CSV.

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
| `DESCRIPTION_LIMIT` | `4000` | Maximum stored description length |
| `JOBSPY_SITES` | `indeed,linkedin` | Comma-separated JobSpy boards |
| `JOBSPY_PROXIES` | empty | `user:pass@host:port,...` for blocked boards |

Set them in the shell (`$env:MAX_RUNTIME_MIN="20"` on Windows) or in the workflow `env:` block.

## Output

`jobs.csv` columns:

```text
title, company, location, source, job_url, description, found_at
```

The SQLite table `seen_jobs` stores the same fields plus `job_url` as the primary key. To start fresh, delete both data files — the next run recreates them.

`reports/latest.md` contains the run mode, new-job count, a per-source table and up to 25 new listings. It is printed into the GitHub Actions step summary on every run.

## Automation

`.github/workflows/run.yml` runs the search twice a day (`08:00` and `20:00` UTC) and commits the updated CSV and database back to the repository. It also writes a run summary, uploads `reports/latest.md` as an artifact and can be triggered manually from the **Actions** tab.

No secrets are required; the workflow uses the default `GITHUB_TOKEN` with `contents: write`.

`ci.yml` runs linting and the test suite on every push and pull request. Dependabot keeps Python and GitHub Actions dependencies up to date.

## Development

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

The tests cover URL normalization, normalization/de-duplication, description truncation, CLI defaults and collector registry integrity. They do not touch the network.

## Limitations

- The Polish boards are scraped from public HTML, so a site redesign can break a collector. Each collector fails independently and the rest of the run continues.
- JobSpy sources (especially LinkedIn and Glassdoor) rate-limit datacenter IPs such as GitHub Actions runners. Local runs usually return more results; proxies help.
- Descriptions are only as complete as the page exposes; some boards return titles without a full description.
- No salary normalization or relevance ranking yet — the output is intentionally a raw, de-duplicated feed.
- `jobs.csv` and `local_jobs.db` grow forever. For long-term use, move them to an actions cache or a separate data branch.
