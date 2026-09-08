"""Record and resolve :class:`~deployments.models.system_message.SystemMessage` rows.

Called from deep inside the refresh pipeline -- error handlers, backoff logic, dataset
validation -- so a problem worth reporting can be raised without those call sites having to
know anything about `update_or_create`, dedupe keys, or the outstanding/resolved lifecycle.
Both functions follow the same never-raise contract as
:mod:`buoy_barn.observability.metrics`: instrumentation and reporting that can break a
refresh are worse than no instrumentation, because they'd fail data collection in order to
report a problem *with* data collection.
"""

import logging

from django.db.models import F
from django.utils import timezone

from deployments.models.system_message import SystemMessage, subject_field

logger = logging.getLogger(__name__)


def record_system_message(  # noqa: PLR0913 - one parameter per SystemMessage field it sets
    subject,
    code,
    message,
    *,
    level,
    constraint_group="",
    context=None,
) -> SystemMessage | None:
    """Upsert a SystemMessage for `subject`, deduped on (subject, code, constraint_group).

    A recurring problem reuses its existing row rather than creating a new one each time it
    is seen -- that's what the unique constraint enforces -- so this always resolves to
    exactly one of "create the row" or "update the row that's already there":

    * On create: `first_seen`/`last_seen` take the model's `timezone.now` default and
      `occurrences` starts at 1, all untouched by this function.
    * On update: `message`, `context` and `level` are overwritten with the latest values
      (an old message about a problem that has since changed shape is not useful), and
      `resolved_at` is cleared. A resolved message getting recorded again means the problem
      came back, and that has to reopen the row -- there's nowhere else for a recurrence to
      go, since the dedupe key admits only one row per (subject, code, constraint_group).

    `occurrences` is bumped in a second, separate statement -- `.filter(pk=...).update(
    occurrences=F("occurrences") + 1)` -- instead of incrementing the Python attribute and
    saving it. `update_or_create`'s `defaults` can only overwrite fields with fixed values,
    it cannot express "whatever is currently in the database, plus one", so a
    read-then-write of `occurrences` here would drop concurrent increments (two workers
    both reading occurrences=4 and both saving 5). The `F()` expression pushes the
    read-and-add into a single UPDATE the database executes atomically, so no increment is
    lost regardless of how many workers report the same problem at once.

    Never raises: this runs inside the refresh pipeline, where letting a reporting failure
    propagate would take down data collection over a problem with *reporting on* data
    collection. Every failure is caught, logged at WARNING with a traceback, and swallowed;
    the caller gets `None` back and keeps going.
    """
    try:
        code_value = str(code)
        column = subject_field(subject)
        now = timezone.now()

        row, created = SystemMessage.objects.update_or_create(
            **{column: subject},
            code=code_value,
            constraint_group=constraint_group,
            defaults={
                "level": level,
                "message": message,
                "context": context or {},
                "last_seen": now,
                "resolved_at": None,
            },
        )

        if not created:
            SystemMessage.objects.filter(pk=row.pk).update(occurrences=F("occurrences") + 1)
            row.refresh_from_db(fields=["occurrences"])
    except Exception:
        logger.warning(
            "Failed to record system message %r for %r",
            code,
            subject,
            exc_info=True,
        )
        return None
    else:
        return row


def resolve_system_messages(subject, *codes, constraint_group=None) -> int:
    """Resolve outstanding messages for `subject` whose code is in `codes`.

    `constraint_group` narrows the resolution to one constraint group when given, including
    the empty string (a subject with no constraint group at all). Left as `None` -- the
    default -- it is not filtered on at all, so every constraint group for this subject and
    these codes is resolved; that's deliberate, since a caller resolving "this dataset is
    reachable again" has no single constraint group to name, and passing `""` there would
    silently miss every message recorded with a real group.

    Only rows that are not already resolved are touched, and the return value is the number
    of rows this call resolved -- not the number matching the filter before it ran.

    Never raises, for the same reason as :func:`record_system_message`: a resolution that
    fails to write must not be allowed to break the refresh path that discovered the problem
    is now over. Returns 0 on failure.
    """
    try:
        column = subject_field(subject)
        code_values = [str(code) for code in codes]

        queryset = SystemMessage.objects.filter(
            **{column: subject},
            code__in=code_values,
            resolved_at__isnull=True,
        )
        if constraint_group is not None:
            queryset = queryset.filter(constraint_group=constraint_group)

        return queryset.update(resolved_at=timezone.now())
    except Exception:
        logger.warning(
            "Failed to resolve system messages %r for %r",
            codes,
            subject,
            exc_info=True,
        )
        return 0
