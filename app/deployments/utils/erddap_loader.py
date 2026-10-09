"""Import a platform and its timeseries from an ERDDAP dataset's metadata.

`plan_import` reads the dataset metadata and works out what would change, without writing
anything, so the admin can show a preview. `apply_import` then makes the changes that were
selected. See `erddap_metadata` for the attribute conventions.
"""

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime

from django.contrib.gis.geos import Point
from django.db import transaction

from ..models import (
    BufferType,
    DataType,
    ErddapDataset,
    ErddapServer,
    Platform,
    TimeSeries,
)
from . import erddap_metadata as metadata
from .erddap_metadata import DatasetInfo

logger = logging.getLogger(__name__)

LOCATION_DIFF_WARN_METERS = 500
# Closer than this, the ERDDAP location is treated as the same as the platform's
LOCATION_SAME_METERS = 1

# Fields on an existing TimeSeries that an import can update
UPDATABLE_FIELDS = ["constraints", *TimeSeries.DATUMS]

CONSTRAINT_KEY = re.compile(r"^(?P<variable>.+?)(?P<operator>=~|!=|<=|>=|=|<|>)$")


class Status:
    NEW = "new"
    UNCHANGED = "existing-unchanged"
    CHANGED = "existing-changed"
    UNABLE = "unable"


@dataclass
class VariablePlan:
    variable: str
    status: str
    data_type: DataType | None = None
    constraints: dict = field(default_factory=dict)
    datums: dict[str, float] = field(default_factory=dict)
    datum_reference: str | None = None
    depth: float | None = None
    warnings: list[str] = field(default_factory=list)
    existing: TimeSeries | None = None
    changes: dict[str, tuple] = field(default_factory=dict)
    # Whether the row is ticked in the preview
    selected: bool = False

    @property
    def long_name(self):
        return self.data_type.long_name if self.data_type else ""


@dataclass
class FieldChange:
    """A platform field ERDDAP has a value for, and whether to change it by default"""

    current: object
    proposed: object
    selected: bool


@dataclass
class ImportPlan:
    server: ErddapServer
    dataset_id: str
    constraints: dict
    platform: Platform | None
    info: DatasetInfo
    location: Point | None = None
    location_source: str = ""
    current_location: Point | None = None
    location_distance: float | None = None
    location_selected: bool = False
    platform_fields: dict[str, FieldChange] = field(default_factory=dict)
    select_new: bool = True
    select_changed: bool = False
    start_time: datetime | None = None
    end_time: datetime | None = None
    buffer_type: BufferType | None = None
    variables: list[VariablePlan] = field(default_factory=list)
    not_in_metadata: list[TimeSeries] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def location_changes(self) -> bool:
        """Would setting the location from ERDDAP change it"""
        return self.location is not None and (
            self.current_location is None
            or self.location_distance is None
            or self.location_distance > LOCATION_SAME_METERS
        )

    @property
    def location_differs(self) -> bool:
        return self.location_distance is not None and self.location_distance > LOCATION_DIFF_WARN_METERS

    def by_status(self, status: str) -> list[VariablePlan]:
        return [row for row in self.variables if row.status == status]

    @property
    def new(self):
        return self.by_status(Status.NEW)

    @property
    def changed(self):
        return self.by_status(Status.CHANGED)

    @property
    def unchanged(self):
        return self.by_status(Status.UNCHANGED)

    @property
    def unable(self):
        return self.by_status(Status.UNABLE)


@dataclass
class ImportResult:
    platform: Platform
    dataset: ErddapDataset
    created: list[TimeSeries]
    updated: list[TimeSeries]
    platform_created: bool
    location_updated: bool
    fields_updated: list[str]


def base_constraints(constraints: dict | None, info: DatasetInfo) -> dict:
    """Constraints with any QC flag constraints removed"""
    base = {}
    for key, value in (constraints or {}).items():
        match = CONSTRAINT_KEY.match(key)
        variable = match.group("variable") if match else key
        if variable in info.variables and metadata.is_flag_variable(info, variable):
            continue
        base[key] = value
    return base


def _depth(constraints: dict) -> float | None:
    try:
        return float(constraints["depth="])
    except (KeyError, TypeError, ValueError):
        return None


def _datums_close(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, abs_tol=1e-6)


def _compare_existing(row: VariablePlan, existing: TimeSeries) -> dict[str, tuple]:
    changes = {}
    if (existing.constraints or {}) != row.constraints:
        changes["constraints"] = (existing.constraints, row.constraints)
    for datum_field, value in row.datums.items():
        current = getattr(existing, datum_field)
        if not _datums_close(current, value):
            changes[datum_field] = (current, value)
    return changes


def _plan_platform(plan: ImportPlan, platform: Platform | None):
    """Which platform fields and location ERDDAP would change.

    A new platform takes everything ERDDAP has. On an existing platform, blank fields
    and a missing location are selected to be filled in, while values that differ are
    only offered: a platform with several datasets shouldn't have its name changed by
    each one.
    """
    defaults = metadata.platform_defaults(plan.info)

    if platform is None:
        plan.platform_fields = {
            name: FieldChange(current=None, proposed=value, selected=True)
            for name, value in defaults.items()
        }
        plan.location_selected = plan.location is not None
        return

    plan.current_location = platform.geom
    plan.location_selected = platform.geom is None and plan.location is not None
    if platform.geom and plan.location:
        plan.location_distance = metadata.distance_meters(platform.geom, plan.location)

    for name, value in defaults.items():
        current = getattr(platform, name)
        if current == value:
            continue
        # Platforms default to a buoy, so a different type is never a blank to fill
        blank = not current and name != "platform_type"
        plan.platform_fields[name] = FieldChange(current=current, proposed=value, selected=blank)


def plan_import(  # noqa: PLR0913
    server: ErddapServer,
    dataset_id: str,
    constraints: dict | None = None,
    platform: Platform | None = None,
    info: DatasetInfo | None = None,
    *,
    select_new: bool = True,
    select_changed: bool = False,
) -> ImportPlan:
    """Work out what importing a dataset would create or change. Nothing is saved.

    `select_new` and `select_changed` are whether new and changed timeseries are ticked
    in the preview by default.
    """
    constraints = dict(constraints or {})
    if info is None:
        info = metadata.fetch_dataset_info(server, dataset_id)

    plan = ImportPlan(
        server=server,
        dataset_id=dataset_id,
        constraints=constraints,
        platform=platform,
        info=info,
        select_new=select_new,
        select_changed=select_changed,
    )
    plan.location, plan.location_source = metadata.platform_location(info, server, constraints)
    if plan.location is None:
        plan.warnings.append("Unable to find a location in the dataset metadata")

    _plan_platform(plan, platform)

    plan.start_time, plan.end_time = metadata.time_range(info)

    buffer_name = info.globals.get("buffer_type")
    if buffer_name:
        plan.buffer_type = BufferType.objects.filter(name=buffer_name).first()
        if plan.buffer_type is None:
            plan.warnings.append(f"Buffer type {buffer_name!r} does not exist")

    _plan_variables(plan)

    return plan


def _existing_timeseries(plan: ImportPlan) -> dict[tuple, TimeSeries]:
    """The platform's timeseries from this dataset, by variable and non-QC constraints"""
    if plan.platform is None or not plan.platform.pk:
        return {}

    existing = plan.platform.timeseries_set.filter(
        dataset__server=plan.server,
        dataset__name=plan.dataset_id,
    ).select_related("data_type")
    return {
        (ts.variable, tuple(sorted(base_constraints(ts.constraints, plan.info).items()))): ts
        for ts in existing
    }


def _plan_variable(
    plan: ImportPlan,
    variable: str,
    aggregates: dict,
) -> tuple[VariablePlan, str | None]:
    """A new timeseries for a variable, and why it can't be imported if it can't"""
    info = plan.info
    attrs = info.variables[variable]
    row = VariablePlan(variable=variable, status=Status.NEW, depth=_depth(plan.constraints))

    qc, qc_warnings = metadata.qartod_constraints(info, variable, aggregates)
    row.constraints = {**plan.constraints, **qc}
    row.warnings.extend(qc_warnings)

    row.datums, datum_warnings = metadata.tidal_datums(info, variable)
    row.warnings.extend(datum_warnings)
    if row.datums:
        row.datum_reference = attrs.get("datum")

    row.data_type, reason = metadata.match_data_type(attrs)
    return row, reason


def _plan_variables(plan: ImportPlan):
    """Plan each data variable, and compare them with the platform's existing timeseries"""
    existing_by_key = _existing_timeseries(plan)
    aggregates, aggregate_warnings = metadata.aggregate_flags(plan.info)
    plan.warnings.extend(aggregate_warnings)

    own_constraints = tuple(sorted(plan.constraints.items()))
    matched = set()
    for variable in metadata.data_variables(plan.info):
        row, reason = _plan_variable(plan, variable, aggregates)
        row.selected = plan.select_new

        existing = existing_by_key.get((variable, own_constraints))
        if existing is not None:
            matched.add(existing.pk)
            row.existing = existing
            row.changes = _compare_existing(row, existing)
            row.status = Status.CHANGED if row.changes else Status.UNCHANGED
            row.selected = bool(row.changes) and plan.select_changed
        elif row.data_type is None:
            row.status = Status.UNABLE
            row.selected = False
            row.warnings.insert(0, reason)

        plan.variables.append(row)

    # Only this constraint group's timeseries, the platform may use the dataset at other
    # depths or stations too
    plan.not_in_metadata = [
        ts
        for (_, constraints), ts in existing_by_key.items()
        if constraints == own_constraints and ts.pk not in matched
    ]


def _save_platform(
    plan: ImportPlan,
    fields: set[str],
    update_location: bool,
    platform_name: str | None,
) -> tuple[Platform, bool]:
    """Create or update the platform, returning it and whether the location was set"""
    platform = plan.platform
    if platform is None:
        if not platform_name:
            raise ValueError("A platform name is needed to create a new platform")
        platform = Platform(name=platform_name, mooring_site_desc="")

    for name, change in plan.platform_fields.items():
        if name in fields:
            setattr(platform, name, change.proposed)

    location_updated = bool(update_location and plan.location_changes)
    if location_updated:
        platform.geom = plan.location

    platform.save()
    return platform, location_updated


def _create_timeseries(
    plan: ImportPlan,
    platform: Platform,
    dataset: ErddapDataset,
    create: set[str],
) -> list[TimeSeries]:
    created = []
    for row in plan.new:
        if row.variable not in create:
            continue
        ts = TimeSeries(
            platform=platform,
            variable=row.variable,
            data_type=row.data_type,
            constraints=row.constraints,
            dataset=dataset,
            depth=row.depth,
            end_time=plan.end_time,
            buffer_type=plan.buffer_type,
            **row.datums,
        )
        if plan.start_time:
            ts.start_time = plan.start_time
        ts.save()
        created.append(ts)
    return created


def _update_timeseries(plan: ImportPlan, update: set[str]) -> list[TimeSeries]:
    updated = []
    for row in plan.changed:
        if row.variable not in update:
            continue
        ts = row.existing
        for name, (_, value) in row.changes.items():
            setattr(ts, name, value)
        ts.save(update_fields=[*row.changes, "update_time"])
        updated.append(ts)
    return updated


def apply_import(  # noqa: PLR0913
    plan: ImportPlan,
    *,
    create: list[str] | None = None,
    update: list[str] | None = None,
    platform_fields: list[str] | None = None,
    update_location: bool | None = None,
    platform_name: str | None = None,
) -> ImportResult:
    """Save the selected parts of an import plan.

    `create` and `update` are the variable names to create new or update existing
    timeseries for, and `platform_fields` the platform fields to set from ERDDAP.
    Anything left as None uses the plan's defaults: every new timeseries is created,
    no existing ones are updated, and only blank platform fields and a missing location
    are filled in.
    """
    if create is None:
        create = [row.variable for row in plan.new]
    if platform_fields is None:
        platform_fields = [name for name, change in plan.platform_fields.items() if change.selected]
    if update_location is None:
        update_location = plan.location_selected

    with transaction.atomic():
        dataset, _ = ErddapDataset.objects.get_or_create(
            name=plan.dataset_id,
            server=plan.server,
        )
        platform, location_updated = _save_platform(
            plan,
            set(platform_fields),
            update_location,
            platform_name,
        )
        created = _create_timeseries(plan, platform, dataset, set(create))
        updated = _update_timeseries(plan, set(update or []))

    return ImportResult(
        platform=platform,
        dataset=dataset,
        created=created,
        updated=updated,
        platform_created=plan.platform is None,
        location_updated=location_updated,
        fields_updated=[name for name in plan.platform_fields if name in platform_fields],
    )


def add_timeseries(platform: Platform, server: str, dataset: str, constraints):
    """Add timeseries for a dataset to an existing platform from the Django shell.

    Prefer the "Import dataset from ERDDAP" action on the platform admin, which shows
    what will change first. See Readme.md.
    """
    erddap_server = ErddapServer.objects.get(base_url=server)
    plan = plan_import(erddap_server, dataset, constraints, platform=platform)

    for row in plan.unable:
        logger.warning(f"{row.variable}: {row.warnings[0]}")

    return apply_import(plan)
