"""Django admin registrations for the deployments app, split by feature.

Every submodule is imported here so `django.contrib.admin.autodiscover()` (which only ever
imports `deployments.admin`, this package) actually runs each module's `@admin.register`
calls -- a submodule left out of this list would silently vanish from the admin with nothing
else noticing. Import order follows the dependency graph: `system_messages` and `displays`
have no dependencies on the rest of this package, `timeseries` depends on `system_messages`,
and `platform` / `erddap` depend on all three; `lookups` stands alone.
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
    MESSAGE_PATHS,
    MessageReach,
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
    "MESSAGE_PATHS",
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
