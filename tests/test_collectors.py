"""Offline tests for all nine collectors. No network, no JobSpy, no Google."""
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

import job_search_pl as j

TERM = "translator"


@pytest.fixture(autouse=True)
def one_term(monkeypatch):
    monkeypatch.setattr(j, "SEARCH_TERMS", [TERM])


HTML_CASES = [
    (j.collect_pracuj, '<a href="/oferta/1">Translator PL</a>', "pracuj.pl", "/oferta/1"),
    (j.collect_justjoinit, '<a href="/job-offer/1">Translator IT</a>', "justjoin.it", "/job-offer/1"),
    (j.collect_nofluffjobs, '<a href="/pl/job/1">Translator NFJ</a>', "nofluffjobs", "/pl/job/1"),
    (j.collect_rocketjobs, '<a href="/oferta/1">Translator Rocket</a>', "rocketjobs", "/oferta/1"),
    (j.collect_bulldogjob, '<a href="/jobs/1">Translator Bulldog</a>', "bulldogjob", "/jobs/1"),
    (j.collect_jooble, f'<a href="/job/1">{TERM} wanted</a>', "jooble", "/job/1"),
    (j.collect_theprotocol, '<a href="/oferta/1">Translator Protocol</a>', "theprotocol", "/oferta/1"),
]


@pytest.mark.parametrize("collector,html,source,path", HTML_CASES)
def test_html_collector_extracts_a_job(monkeypatch, collector, html, source, path):
    monkeypatch.setattr(j, "request_page", lambda url: html)
    jobs = collector()
    assert len(jobs) == 1
    assert jobs[0]["source"] == source
    assert path in jobs[0]["job_url"]
    assert jobs[0]["job_url"].startswith("https://")
    assert jobs[0]["title"]


@pytest.mark.parametrize("collector,_html,source,_path", HTML_CASES)
def test_html_collector_ignores_unrelated_links(monkeypatch, collector, _html, source, _path):
    monkeypatch.setattr(j, "request_page", lambda url: '<a href="/privacy">Privacy</a>')
    assert collector() == []


def test_google_discovery_parses_search_results(monkeypatch):
    html = ('<div class="MjjYud"><a href="/url?q=https://pracuj.pl/oferta/1&sa=t">'
            '<h3>Translator job</h3></a></div>')
    monkeypatch.setattr(j, "request_page", lambda url: html)
    jobs = j.collect_google_results()
    assert len(jobs) == 1
    assert jobs[0]["source"] == "search-discovery"
    assert jobs[0]["job_url"].startswith("https://pracuj.pl/")


def test_jobspy_collector_maps_dataframe_rows(monkeypatch):
    frame = pd.DataFrame([{
        "title": "Translator", "company": "Acme", "location": "Warsaw",
        "site": "indeed", "job_url": "https://example.test/job",
        "description": "Translate documents",
    }])
    fake = types.ModuleType("jobspy")
    fake.scrape_jobs = lambda **_kwargs: frame
    monkeypatch.setitem(sys.modules, "jobspy", fake)
    jobs = j.collect_jobspy()
    assert len(jobs) == 1
    assert jobs[0]["company"] == "Acme"
    assert jobs[0]["source"] == "indeed"


def test_jobspy_failure_does_not_stop_the_run(monkeypatch):
    fake = types.ModuleType("jobspy")

    def explode(**_kwargs):
        raise RuntimeError("blocked")

    fake.scrape_jobs = explode
    monkeypatch.setitem(sys.modules, "jobspy", fake)
    assert j.collect_jobspy() == []


def test_request_page_retries_and_respects_time_budget(monkeypatch):
    calls = []

    class Response:
        status_code = 200
        text = "<html>ok</html>"

    def fake_get(url, **_kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return Response()

    monkeypatch.setattr(j.requests, "get", fake_get)
    monkeypatch.setattr(j.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(j, "out_of_time", lambda: False)
    assert j.request_page("https://example.test") == "<html>ok</html>"
    assert len(calls) == 2


def test_workflow_keeps_the_token_out_of_the_url():
    root = Path(j.__file__).resolve().parent
    workflow = (root / ".github" / "workflows" / "run.yml").read_text(encoding="utf-8")
    assert "x-access-token:" not in workflow
    assert "http.extraheader" in workflow
    assert "secrets.GITHUB_TOKEN" in workflow
