"""Tests for the two `/ht/` health-check routes in `buoy_barn/urls.py`.

Both routes are `HealthCheckView.as_view(checks=[...])`, and Django's `View.as_view` stashes
those kwargs on the returned view function as `view_initkwargs`, so the configured `checks`
list can be inspected via `resolve()` without ever calling the view -- no live check runs, no
database, no broker or worker required.

The regression these guard: `/ht/` backs the Kubernetes *web* liveness probe. The Celery ping
belongs only on `/ht/celery/`, which nothing restarts (see the warning in urls.py) -- if the
Celery check ever migrated onto `/ht/`, a merely-busy (not dead) worker could get web pods
killed. And the ping's timeout is deliberately 10s, not the library's 1s default, precisely
because a busy worker is not a dead one; if a future edit drops the `timeout` kwarg, that
regresses silently unless something asserts the value.
"""

from datetime import timedelta

from django.urls import resolve


def _checks_for(path):
    """The `(dotted_path, options)` pairs configured for `path`, plain strings normalized to `({}, )`."""
    raw = resolve(path).func.view_initkwargs["checks"]
    return [check if isinstance(check, tuple) else (check, {}) for check in raw]


def test_ht_does_not_run_the_celery_ping():
    names = [name for name, _options in _checks_for("/ht/")]

    assert not any("celery" in name.lower() for name in names)


def test_ht_celery_runs_only_the_celery_ping():
    checks = _checks_for("/ht/celery/")

    assert [name for name, _options in checks] == ["health_check.contrib.celery.Ping"]


def test_ht_celery_ping_uses_a_ten_second_timeout():
    """A regression here means a future edit quietly fell back to Ping's 1-second default,

    which is tuned for a healthy worker replying fast, not for tolerating a busy one --
    exactly the false-positive this endpoint's longer timeout exists to avoid.
    """
    ((_name, options),) = _checks_for("/ht/celery/")

    assert options["timeout"] == timedelta(seconds=10)
