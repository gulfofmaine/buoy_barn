"""The ERDDAP outcome vocabulary: the `Outcome` enum and how each value is handled."""

from enum import StrEnum

from deployments.models import SystemMessage

# Returned by a handler that did not recognise the error, so the caller keeps looking.
# Falsy, so `if handle_http_errors(...): return` still means "handled".
NOT_HANDLED = ""


class Outcome(StrEnum):
    """Every outcome the refresh path can report, produced in error_handling.py or refresh.py.

    An enum rather than bare strings so a handler cannot report a mistyped outcome, which
    would be validated away to "other" by
    :func:`buoy_barn.observability.metrics.erddap_outcomes` and quietly leave the real
    failure off every dashboard.

    ``StrEnum``, not ``(str, Enum)``: members must equal their own string value, since they
    are tested for truthiness against :data:`NOT_HANDLED` and handed to the metrics facade
    as an attribute. ``(str, Enum)`` would make ``str(Outcome.NO_ROWS)`` be
    ``"Outcome.NO_ROWS"`` instead.
    """

    # Named by refresh.py around the fetch, not by a handler.
    SUCCESS = "success"
    EMPTY_DATAFRAME = "empty_dataframe"
    TIMEOUT = "timeout"
    BACKOFF = "backoff"
    OS_ERROR = "os_error"
    VALUE_ERROR = "value_error"
    UNKNOWN_ERROR = "unknown_error"

    # Returned by the handlers in error_handling.py.
    NO_ROWS = "no_rows"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    TIME_RANGE_RETIRED = "time_range_retired"
    TIME_RANGE_REPORTED = "time_range_reported"
    CONSTRAINT_OUT_OF_RANGE = "constraint_out_of_range"
    NO_MATCHING_TIME = "no_matching_time"
    UNRECOGNIZED_VARIABLE = "unrecognized_variable"
    UNRECOGNIZED_CONSTRAINT = "unrecognized_constraint"
    SERVER_ERROR = "server_error"


# Plain strings: what `buoy_barn.observability.metrics` validates the outcome attribute against.
OUTCOMES = frozenset(outcome.value for outcome in Outcome)

# The level a handler logs at says whether its outcome is benign (only
# `handle_500_no_rows_error` logs at INFO). Keep this set in sync with that, not the reverse.
BENIGN_OUTCOMES = frozenset({Outcome.SUCCESS.value, Outcome.NO_ROWS.value})

# Non-benign outcomes worth a SystemMessage, mapped to the (code, level) to record it at. A
# dict forces a decision here.
#
# `time_range_retired` is absent on purpose: `handle_500_time_range_error` already records
# `end_time_retired` per affected timeseries, the more precise subject. See
# `HANDLED_ELSEWHERE` below for that and every other outcome recorded outside this map.
FETCH_FAILURE_MESSAGES: dict[str, tuple[str, str]] = {
    Outcome.FORBIDDEN: (SystemMessage.Code.FORBIDDEN, SystemMessage.Level.DANGER),
    Outcome.NOT_FOUND: (SystemMessage.Code.NOT_FOUND, SystemMessage.Level.DANGER),
    Outcome.UNRECOGNIZED_VARIABLE: (
        SystemMessage.Code.UNRECOGNIZED_VARIABLE,
        SystemMessage.Level.WARNING,
    ),
    Outcome.UNRECOGNIZED_CONSTRAINT: (
        SystemMessage.Code.UNRECOGNIZED_CONSTRAINT,
        SystemMessage.Level.WARNING,
    ),
    Outcome.SERVER_ERROR: (SystemMessage.Code.SERVER_ERROR, SystemMessage.Level.WARNING),
    Outcome.UNKNOWN_ERROR: (SystemMessage.Code.UNKNOWN_ERROR, SystemMessage.Level.WARNING),
    Outcome.CONSTRAINT_OUT_OF_RANGE: (
        SystemMessage.Code.CONSTRAINT_OUT_OF_RANGE,
        SystemMessage.Level.WARNING,
    ),
    Outcome.NO_MATCHING_TIME: (
        SystemMessage.Code.NO_MATCHING_TIME,
        SystemMessage.Level.WARNING,
    ),
    Outcome.TIME_RANGE_REPORTED: (
        SystemMessage.Code.TIME_RANGE_REPORTED,
        SystemMessage.Level.INFO,
    ),
}

# Outcomes recorded somewhere other than `FETCH_FAILURE_MESSAGES`, with where. Listing them
# is what lets the exhaustiveness test tell "handled elsewhere" from "forgotten".
HANDLED_ELSEWHERE: dict[str, str] = {
    Outcome.TIME_RANGE_RETIRED: "recorded per-timeseries by handle_500_time_range_error",
    Outcome.TIMEOUT: "recorded as backoff_increased by refresh_dataset's BackoffError catch",
    Outcome.BACKOFF: "recorded as backoff_increased by refresh_dataset's BackoffError catch",
    Outcome.OS_ERROR: "logged with exc_info; reaches Sentry/log.records, not a SystemMessage",
    Outcome.EMPTY_DATAFRAME: "tracked only by the rows metric, to avoid routine-empty noise",
    Outcome.VALUE_ERROR: "not produced by any handler; per-series ValueErrors are logged directly",
}

# Derived from `FETCH_FAILURE_MESSAGES`, so "what's recorded on failure" and "what's
# resolved on success" cannot drift apart.
FETCH_FAILURE_CODES = tuple(code for code, _level in FETCH_FAILURE_MESSAGES.values())

# `backoff_increased` is recorded in `refresh_dataset`, not through the map above, but a
# successful fetch means the backoff no longer applies to this group either.
RESOLVED_ON_SUCCESS = (*FETCH_FAILURE_CODES, SystemMessage.Code.BACKOFF_INCREASED)
