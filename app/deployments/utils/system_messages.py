"""Record and resolve :class:`~deployments.models.system_message.SystemMessage` rows.

Called from deep inside the refresh pipeline, so neither function ever raises: failing data
collection in order to report a problem *with* data collection is worse than not reporting.
Every failure is logged at WARNING and swallowed.
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

    On update, `message`, `context` and `level` take the latest values and `resolved_at` is
    cleared. The dedupe key admits one row per key, so a recurrence has nowhere to go except
    back into the row that was resolved.

    `occurrences` is bumped by a separate `F()` UPDATE because `update_or_create`'s
    `defaults` can only write fixed values; reading it here and saving the result would drop
    concurrent increments.

    Returns `None` if recording failed.
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

    `constraint_group=None` (the default) means *any* group, not the empty one: it is not
    filtered on at all. Passing `""` instead narrows to the group with no constraints, which
    would silently miss every message recorded against a real group.

    Returns the number of rows this call resolved, or 0 if resolving failed.
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
