"""Django admin registrations for the deployments app, split by feature.

Submodules are imported here so `django.contrib.admin.autodiscover()` (which only ever
imports `deployments.admin`) run each module's `@admin.register`
calls.
"""

from .displays import timeseries_status
from .erddap import ErddapDatasetAdmin, ErddapServerAdmin, RefreshStatusListFilter
from .lookups import BufferTypeAdmin, DataTypeAdmin
from .platform import (
    AlertInline,
    PlatformAdmin,
    PlatformLinkInline,
    ProgramAttributionInline,
    TimeseriesActiveFilter,
)
from .system_messages import (
    SUBJECT_KINDS,
    MessageReach,
    SubjectKind,
    SystemMessageAdmin,
    SystemMessageBadge,
    SystemMessageChangeList,
    SystemMessageListFilter,
    SystemMessageRow,
    SystemMessageSidebarMixin,
    SystemMessageStateFilter,
    SystemMessageSubjectFilter,
    annotate_system_message_badges,
    build_system_message_rows,
    compute_message_reach,
    messages_reaching,
    outstanding_messages_exist,
    system_message_rank,
    system_message_status,
)
from .timeseries import (
    FloodLevelInline,
    TimeSeriesAdmin,
    TimeSeriesInline,
    TimesiersStatusListFilter,
)

__all__ = [
    "SUBJECT_KINDS",
    "AlertInline",
    "BufferTypeAdmin",
    "DataTypeAdmin",
    "ErddapDatasetAdmin",
    "ErddapServerAdmin",
    "FloodLevelInline",
    "MessageReach",
    "PlatformAdmin",
    "PlatformLinkInline",
    "ProgramAttributionInline",
    "RefreshStatusListFilter",
    "SubjectKind",
    "SystemMessageAdmin",
    "SystemMessageBadge",
    "SystemMessageChangeList",
    "SystemMessageListFilter",
    "SystemMessageRow",
    "SystemMessageSidebarMixin",
    "SystemMessageStateFilter",
    "SystemMessageSubjectFilter",
    "TimeSeriesAdmin",
    "TimeSeriesInline",
    "TimeseriesActiveFilter",
    "TimesiersStatusListFilter",
    "annotate_system_message_badges",
    "build_system_message_rows",
    "compute_message_reach",
    "messages_reaching",
    "outstanding_messages_exist",
    "system_message_rank",
    "system_message_status",
    "timeseries_status",
]
