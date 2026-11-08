import job_search_pl as bot


def test_normalize_url_strips_tracking_and_fragment():
    url = "HTTPS://Example.COM/Job/123/?utm_source=x&gclid=y&id=7#apply"

    assert bot.normalize_url(url) == "https://example.com/Job/123?id=7"


def test_normalize_url_leaves_non_absolute_urls_alone():
    assert bot.normalize_url("  /job/1  ") == "/job/1"


def test_normalize_jobs_dedupes_url_variants():
    jobs = [
        bot.make_job("Translator", "ACME", "Poland", "pracuj", "https://x.pl/oferta/1?utm_source=a"),
        bot.make_job("Translator", "ACME", "Poland", "pracuj", "https://x.pl/oferta/1?utm_source=b"),
    ]

    frame = bot.normalize_jobs(jobs)

    assert len(frame) == 1
    assert frame.iloc[0]["job_url"] == "https://x.pl/oferta/1"


def test_normalize_jobs_returns_expected_columns_for_empty_input():
    frame = bot.normalize_jobs([])

    assert list(frame.columns) == [
        "title",
        "company",
        "location",
        "source",
        "job_url",
        "description",
    ]


def test_make_job_cleans_whitespace_and_missing_values():
    job = bot.make_job("  Senior   Translator ", None, None, "pracuj", "https://x.pl/1")

    assert job["title"] == "Senior Translator"
    assert job["company"] == ""
    assert job["location"] == ""


def test_description_is_truncated(monkeypatch):
    monkeypatch.setattr(bot, "DESCRIPTION_LIMIT", 10)
    frame = bot.normalize_jobs(
        [bot.make_job("Translator", "ACME", "Poland", "pracuj", "https://x.pl/1", "x" * 100)]
    )

    assert len(frame.iloc[0]["description"]) == 10


def test_parse_args_defaults():
    args = bot.parse_args([])

    assert args.dry_run is False
    assert args.sources is None
    assert args.limit is None


def test_collector_keys_are_unique():
    keys = [key for key, _, _ in bot.COLLECTORS]

    assert len(keys) == len(set(keys))
