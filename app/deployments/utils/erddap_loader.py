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

    @property
    def long_name(self):
        return self.data_type.long_name if self.data_type else ""


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
    platform_fields: dict = field(default_factory=dict)
    platform_field_conflicts: dict[str, tuple] = field(default_factory=dict)
    start_time: datetime | None = None
    end_time: datetime | None = None
    buffer_type: BufferType | None = None
    variables: list[VariablePlan] = field(default_factory=list)
    not_in_metadata: list[TimeSeries] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

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
    defaults = metadata.platform_defaults(plan.info)

    if platform is None:
        plan.platform_fields = defaults
        return

    plan.current_location = platform.geom
    if platform.geom and plan.location:
        plan.location_distance = metadata.distance_meters(platform.geom, plan.location)

    for name, value in defaults.items():
        current = getattr(platform, name)
        if name == "platform_type":
            # Platforms default to a buoy, so only suggest a different type
            if current != value:
                plan.platform_field_conflicts[name] = (current, value)
        elif not current:
            plan.platform_fields[name] = value
        elif current != value:
            plan.platform_field_conflicts[name] = (current, value)


def plan_import(
    server: ErddapServer,
    dataset_id: str,
    constraints: dict | None = None,
    platform: Platform | None = None,
    info: DatasetInfo | None = None,
) -> ImportPlan:
    """Work out what importing a dataset would create or change. Nothing is saved."""
    constraints = dict(constraints or {})
    if info is None:
        info = metadata.fetch_dataset_info(server, dataset_id)

    plan = ImportPlan(
        server=server,
        dataset_id=dataset_id,
        constraints=constraints,
        platform=platform,
        info=info,
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

    existing_by_key = {}
    if platform is not None and platform.pk:
        existing = platform.timeseries_set.filter(
            dataset__server=server,
            dataset__name=dataset_id,
        ).select_related("data_type")
        for ts in existing:
            key = (ts.variable, tuple(sorted(base_constraints(ts.constraints, info).items())))
            existing_by_key[key] = ts

    aggregates, aggregate_warnings = metadata.aggregate_flags(info)
    plan.warnings.extend(aggregate_warnings)

    matched = set()
    for variable in metadata.data_variables(info):
        attrs = info.variables[variable]
        row = VariablePlan(variable=variable, status=Status.NEW, depth=_depth(constraints))

        qc, qc_warnings = metadata.qartod_constraints(info, variable, aggregates)
        row.constraints = {**constraints, **qc}
        row.warnings.extend(qc_warnings)

        row.datums, datum_warnings = metadata.tidal_datums(info, variable)
        row.warnings.extend(datum_warnings)
        if row.datums:
            row.datum_reference = attrs.get("datum")

        row.data_type, reason = metadata.match_data_type(attrs)

        key = (variable, tuple(sorted(constraints.items())))
        existing = existing_by_key.get(key)
        if existing is not None:
            matched.add(existing.pk)
            row.existing = existing
            row.changes = _compare_existing(row, existing)
            row.status = Status.CHANGED if row.changes else Status.UNCHANGED
        elif row.data_type is None:
            row.status = Status.UNABLE
            row.warnings.insert(0, reason)

        plan.variables.append(row)

    plan.not_in_metadata = [ts for ts in existing_by_key.values() if ts.pk not in matched]

    return plan


def apply_import(  # noqa: PLR0913
    plan: ImportPlan,
    *,
    create: list[str] | None = None,
    update: list[str] | None = None,
    update_location: bool = False,
    platform_name: str | None = None,
) -> ImportResult:
    """Save the selected parts of an import plan.

    `create` and `update` are the variable names to create new or update existing
    timeseries for. By default every new timeseries is created and none are updated.
    """
    create = {row.variable for row in plan.new} if create is None else set(create)
    update = set(update or [])

    with transaction.atomic():
        dataset, _ = ErddapDataset.objects.get_or_create(
            name=plan.dataset_id,
            server=plan.server,
        )

        platform = plan.platform
        platform_created = platform is None
        location_updated = False

        if platform is None:
            if not platform_name:
                raise ValueError("A platform name is needed to create a new platform")
            platform = Platform(name=platform_name, mooring_site_desc="")
            for name, value in plan.platform_fields.items():
                setattr(platform, name, value)
            platform.geom = plan.location
            location_updated = plan.location is not None
            platform.save()
        else:
            for name, value in plan.platform_fields.items():
                setattr(platform, name, value)
            if plan.location and (platform.geom is None or update_location):
                platform.geom = plan.location
                location_updated = True
            platform.save()

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

        updated = []
        for row in plan.changed:
            if row.variable not in update:
                continue
            ts = row.existing
            for name, (_, value) in row.changes.items():
                setattr(ts, name, value)
            ts.save(update_fields=[*row.changes, "update_time"])
            updated.append(ts)

    return ImportResult(
        platform=platform,
        dataset=dataset,
        created=created,
        updated=updated,
        platform_created=platform_created,
        location_updated=location_updated,
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
