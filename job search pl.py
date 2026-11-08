"""Compatibility entry point.

The scheduled workflow still calls ``python "job search pl.py"``. The implementation
lives in ``job_search_pl.py``; this shim will be removed once the workflow is updated.
"""

from job_search_pl import main

if __name__ == "__main__":
    raise SystemExit(main())
