"""OpenTelemetry metrics bootstrap.

This module owns the ``MeterProvider`` for the current process. Everything else in the
package goes through :func:`get_meter`; nothing else should build SDK objects.

Environment variables
---------------------
This is the authoritative list of what the observability layer reads. Standard ``OTEL_*``
variables are consumed by the SDK itself, so they behave exactly as upstream documents
them.

``OTEL_EXPORTER_OTLP_ENDPOINT`` (or ``OTEL_EXPORTER_OTLP_METRICS_ENDPOINT``)
    Base URL of the OTLP collector, e.g. ``http://otel-collector:4318``. This is the
    switch: when neither is set the whole layer is a no-op: no exporter, no
    background thread, and every recording function returns immediately. Nothing raises
    and nothing blocks, so an unconfigured deployment behaves exactly as it did before
    this package existed.
``OTEL_SERVICE_NAME``
    Service name reported to the collector. Defaults to ``buoy-barn``.
``OTEL_METRIC_EXPORT_INTERVAL``
    Export period in milliseconds, read by ``PeriodicExportingMetricReader``. Defaults to
    60000 upstream; there is no reason to change it here.
``OTEL_RESOURCE_ATTRIBUTES``
    Extra resource attributes, merged by ``Resource.create``.
``BUOY_BARN_OTEL_ROLE``
    Which kind of process this is -- ``web``, ``worker``, ``beat``, ``flower``, ``mqtt``
    or ``exporter``. Becomes the ``buoybarn.role`` resource attribute so Prometheus can
    split metrics by process type. Guessed from ``sys.argv`` when unset.
``BUOY_BARN_SENTRY_METRIC_MIRROR``
    Read by :mod:`buoy_barn.observability.metrics`, not here. Off by default; see that
    module for what it mirrors and why it is off.
``DJANGO_ENV``
    When it equals ``test`` the layer is forced off, matching how ``settings.py`` disables
    Sentry, so the suite never starts an exporter thread.

Why this looks the way it does
------------------------------
Buoy Barn runs granian with ``--workers 4`` and Celery with the default prefork pool, so
metrics are recorded from many processes per pod. Three properties of the OTel SDK make
the naive implementation fail silently:

1. The SDK is not fork-safe. ``PeriodicExportingMetricReader`` runs a background thread,
   and threads do not survive ``fork()``. A provider built in the Celery parent gives
   every prefork child a dead exporter.
2. An "already configured" flag would be *inherited* across ``fork()``, so children would
   skip re-initialising and inherit that dead exporter anyway. The guard is therefore
   keyed on :func:`os.getpid`, not on a bool.
3. ``opentelemetry.metrics.set_meter_provider`` is once-only and its internal "already
   set" flag is *also* inherited across ``fork()``. So even correct child-side setup gets
   silently ignored if the parent ever called it.

Point 3 is why this module keeps its own provider on :data:`_state` instead of relying on
the global one. ``set_meter_provider`` is still called on a best-effort basis so that any
future ``opentelemetry-instrumentation-*`` package finds a provider, but nothing here
depends on that call taking effect.

Initialisation is lazy: the first metric recorded in a process builds that process's
provider. That mechanism covers granian's workers, Celery's forked children, beat,
the MQTT command and the metrics exporter without per-process-type wiring, and it means a
``manage.py migrate`` never starts an exporter because it never records anything.
"""

import atexit
import logging
import os
import socket
import sys

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_NAME = "buoy-barn"
METER_NAME = "buoy_barn"

#: Roles we recognise for the ``buoybarn.role`` resource attribute.
ROLES = frozenset({"web", "worker", "beat", "flower", "mqtt", "exporter", "unknown"})

#: Fallback role detection, in priority order, used when BUOY_BARN_OTEL_ROLE is unset.
#: Checked against the whole command line, so ambiguity is resolved by ordering: the
#: management commands name themselves, and the web servers are matched before any Celery
#: subcommand because granian is started with ``--workers 4`` (Dockerfile ``CMD``) and would
#: otherwise be reported as a Celery worker.
_ARGV_ROLE_HINTS: tuple[tuple[str, str], ...] = (
    ("erddap_mqtt", "mqtt"),
    ("export_metrics", "exporter"),
    ("granian", "web"),
    ("runserver", "web"),
)

#: Celery subcommands, consulted only when the command line is actually Celery's. Keeping
#: them separate is what stops a bare word like "worker" from matching another program's
#: flags.
_CELERY_ROLE_HINTS: tuple[tuple[str, str], ...] = (
    ("beat", "beat"),
    ("flower", "flower"),
    ("worker", "worker"),
)


class _State:
    """Per-process metrics state.

    Deliberately an object rather than a handful of module-level names: this state is
    rebuilt after every ``fork()``, and keeping it together makes "which pid does this
    provider belong to?" one field instead of several globals that could drift apart.
    """

    def __init__(self) -> None:
        self.provider = None
        #: PID ``provider`` was built for. Never a bool -- see the module docstring.
        self.configured_pid: int | None = None
        self.atexit_registered = False
        self.warned_unavailable = False
        #: PID whose provider build already failed, so it is not retried. Memoizing the
        #: failure is not just an optimisation: `configure` logs when a build fails, the
        #: metrics log handler records that log, and recording reaches back into
        #: `configure` -- so a retried failure is an unbounded recursion.
        self.build_failed_pid: int | None = None
        #: True while `configure` is running, so logging raised from inside it cannot
        #: re-enter. Not pid-keyed: it is only ever true within one call on one thread, and
        #: a `fork()` mid-configure would leave the child a copy it must ignore anyway.
        self.configuring = False


_state = _State()


def endpoint() -> str | None:
    """Return the configured OTLP endpoint, or None when metrics are switched off."""
    return os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT") or os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    )


def enabled() -> bool:
    """Is the metrics layer switched on for this process?"""
    if os.environ.get("DJANGO_ENV", "").lower() == "test":
        return False
    return bool(endpoint())


def guess_role() -> str:
    """Best-effort guess at what kind of process this is, from the command line."""
    role = os.environ.get("BUOY_BARN_OTEL_ROLE", "").strip().lower()
    if role in ROLES:
        return role
    if role:
        logger.warning("Unrecognized BUOY_BARN_OTEL_ROLE %r; reporting 'unknown'", role)
        return "unknown"

    argv = " ".join(sys.argv)
    for needle, guessed in _ARGV_ROLE_HINTS:
        if needle in argv:
            return guessed
    if "celery" in argv:
        for needle, guessed in _CELERY_ROLE_HINTS:
            if needle in argv:
                return guessed
    return "unknown"


def _app_version() -> str:
    """Version string for the ``service.version`` resource attribute."""
    try:
        from django.conf import settings  # noqa: PLC0415

        return str(settings.APP_VERSION)
    except Exception:
        # Resource attributes are cosmetic; never let one break process startup.
        return "unknown"


def _build_resource(role: str):
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415

    # HOSTNAME is the pod name under Kubernetes. Including the pid keeps prefork children
    # and granian workers distinguishable rather than clobbering each other's series.
    hostname = os.environ.get("HOSTNAME") or socket.gethostname()
    return Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME") or DEFAULT_SERVICE_NAME,
            "service.version": _app_version(),
            "service.instance.id": f"{hostname}-{os.getpid()}",
            "buoybarn.role": role,
        },
    )


def _build_provider(role: str):
    """Build a MeterProvider, or return None if the SDK is unusable here."""
    try:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # noqa: PLC0415
            OTLPMetricExporter,
        )
        from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader  # noqa: PLC0415
    except ImportError:
        if not _state.warned_unavailable:
            # Set before logging, not after: the log record travels through the metrics log
            # handler, which can lead back here before the flag would have been set.
            _state.warned_unavailable = True
            logger.warning("OpenTelemetry packages are unavailable; metrics are disabled")
        return None

    try:
        # Endpoint and export interval both come from the standard OTEL_* env vars.
        reader = PeriodicExportingMetricReader(OTLPMetricExporter())
        return MeterProvider(resource=_build_resource(role), metric_readers=[reader])
    except Exception:
        logger.exception("Could not configure OpenTelemetry metrics; continuing without them")
        return None


def _publish_globally(provider) -> None:
    """Best-effort ``set_meter_provider`` so contrib instrumentation can find a provider.

    A no-op in a forked child whose parent already set the global provider -- which is
    exactly why callers use :func:`get_meter` rather than the global API.
    """
    try:
        from opentelemetry import metrics as otel_metrics  # noqa: PLC0415

        otel_metrics.set_meter_provider(provider)
    except Exception:
        logger.debug("Global meter provider was already set; using the local provider")


def configure(role: str | None = None) -> bool:
    """Build this process's MeterProvider if it does not have one yet.

    Idempotent per process. Returns True when a usable provider exists afterwards, and
    False when metrics are switched off or the SDK could not be set up -- callers treat
    False as "do nothing", never as an error.

    A failed build is remembered for the life of the process and never retried, and the
    call is guarded against re-entry, because setup failures are *logged* and log records
    are themselves recorded as a metric: without both guards one failure recurses until the
    stack runs out, for every log record emitted.
    """
    pid = os.getpid()
    if _state.configured_pid == pid and _state.provider is not None:
        return True

    if _state.build_failed_pid == pid or _state.configuring:
        return False

    if not enabled():
        return False

    _state.configuring = True
    try:
        resolved_role = role or guess_role()
        provider = _build_provider(resolved_role)
        if provider is None:
            _state.build_failed_pid = pid
            return False

        _state.provider = provider
        _state.configured_pid = pid
        _publish_globally(provider)

        if not _state.atexit_registered:
            atexit.register(shutdown)
            _state.atexit_registered = True

        logger.info(
            "OpenTelemetry metrics enabled (role=%s, endpoint=%s)",
            resolved_role,
            endpoint(),
        )
        return True
    finally:
        _state.configuring = False


def get_meter():
    """Return a Meter for this process, configuring lazily. None when switched off."""
    if not configure():
        return None
    return _state.provider.get_meter(METER_NAME)


def force_flush(timeout_millis: int = 5000) -> None:
    """Push whatever is buffered to the collector right now."""
    if _state.provider is None or _state.configured_pid != os.getpid():
        return
    try:
        _state.provider.force_flush(timeout_millis=timeout_millis)
    except Exception:
        logger.debug("Failed to flush metrics", exc_info=True)


def shutdown(timeout_millis: int = 5000) -> None:
    """Flush and tear down this process's provider.

    Worth calling explicitly when a process is about to exit -- a prefork child that dies
    without this loses up to a whole export interval of metrics.
    """
    if _state.provider is None or _state.configured_pid != os.getpid():
        return

    provider = _state.provider
    _state.provider = None
    _state.configured_pid = None
    try:
        provider.shutdown(timeout_millis=timeout_millis)
    except Exception:
        logger.debug("Failed to shut down metrics provider", exc_info=True)


def reset_for_testing(provider=None) -> None:
    """Swap in a provider (or clear it) from tests. Not for production use."""
    _state.provider = provider
    _state.configured_pid = os.getpid() if provider is not None else None
    _state.build_failed_pid = None
    _state.configuring = False
    _state.warned_unavailable = False
