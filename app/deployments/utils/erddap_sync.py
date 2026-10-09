"""Sync a platform with every ERDDAP dataset its timeseries already use.

`plan_sync` re-plans each dataset and set of constraints on the platform with
`erddap_loader.plan_import`, fetching each dataset's metadata once. Datasets can disagree
about the platform's fields and location, so rather than a single proposed value each one
becomes a choice between keeping the current value and each value ERDDAP has.
`apply_sync` then saves what was chosen.
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field

import requests
from django.db import transaction

from ..models import ErddapDataset, Platform, TimeSeries
from . import erddap_metadata as metadata
from .erddap_loader import (
    LOCATION_DIFF_WARN_METERS,
    LOCATION_SAME_METERS,
    ImportPlan,
    apply_import,
    base_constraints,
    plan_import,
)

KEEP = ""


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode(), usedforsecurity=False).hexdigest()[:10]


@dataclass
class SyncGroup:
    """One dataset and set of (non-QC) constraints used by the platform"""

    id: str
    dataset: ErddapDataset
    constraints: dict
    plan: ImportPlan

    @property
    def label(self) -> str:
        if not self.constraints:
            return str(self.dataset)
        return f"{self.dataset} {json.dumps(self.constraints)}"


@dataclass
class DatasetError:
    dataset: ErddapDataset
    message: str


@dataclass
class Option:
    """A value ERDDAP has for a platform field or the location, and where it came from"""

    id: str
    value: object
    sources: list[str] = field(default_factory=list)
    distance: float | None = None

    @property
    def far(self) -> bool:
        return self.distance is not None and self.distance > LOCATION_DIFF_WARN_METERS


@dataclass
class Choice:
    """Keep a platform field (or the location) as it is, or set it to one of the options"""

    name: str
    current: object
    options: list[Option] = field(default_factory=list)
    default: str = KEEP

    def option(self, option_id: str | None) -> Option | None:
        return next((option for option in self.options if option.id == option_id), None)

    @property
    def differs(self) -> bool:
        return any(option.far for option in self.options)


@dataclass
class SyncPlan:
    platform: Platform
    groups: list[SyncGroup] = field(default_factory=list)
    errors: list[DatasetError] = field(default_factory=list)
    fields: list[Choice] = field(default_factory=list)
    location: Choice | None = None


@dataclass
class SyncResult:
    platform: Platform
    created: list[TimeSeries]
    updated: list[TimeSeries]
    datasets: list[ErddapDataset]
    fields_updated: list[str]
    location_updated: bool


def _timeseries_by_dataset(platform: Platform) -> dict[ErddapDataset, list[TimeSeries]]:
    by_dataset = defaultdict(list)
    for ts in platform.timeseries_set.select_related("dataset__server"):
        by_dataset[ts.dataset].append(ts)
    return dict(sorted(by_dataset.items(), key=lambda item: (str(item[0].server), item[0].name)))


def _plan_dataset(
    platform: Platform,
    dataset: ErddapDataset,
    timeseries: list[TimeSeries],
) -> list[SyncGroup]:
    info = metadata.fetch_dataset_info(dataset.server, dataset.name)
    constraint_sets = {
        json.dumps(base_constraints(ts.constraints, info), sort_keys=True) for ts in timeseries
    }

    groups = []
    for key in sorted(constraint_sets):
        constraints = json.loads(key)
        plan = plan_import(
            dataset.server,
            dataset.name,
            constraints,
            platform,
            info=info,
            select_new=False,
            select_changed=True,
        )
        group_id = _short_hash(f"{dataset.server_id}|{dataset.name}|{key}")
        groups.append(SyncGroup(id=group_id, dataset=dataset, constraints=constraints, plan=plan))
    return groups


def _field_choices(platform: Platform, groups: list[SyncGroup]) -> list[Choice]:
    choices: dict[str, Choice] = {}
    for group in groups:
        for name, change in group.plan.platform_fields.items():
            choice = choices.setdefault(name, Choice(name=name, current=getattr(platform, name)))
            option_id = _short_hash(repr(change.proposed))
            option = choice.option(option_id)
            if option is None:
                option = Option(id=option_id, value=change.proposed)
                choice.options.append(option)
            option.sources.append(group.label)

    for choice in choices.values():
        blank = not choice.current and choice.name != "platform_type"
        if blank and len(choice.options) == 1:
            choice.default = choice.options[0].id

    return list(choices.values())


def _location_choice(platform: Platform, groups: list[SyncGroup]) -> Choice | None:
    choice = Choice(name="location", current=platform.geom)
    for group in groups:
        plan = group.plan
        if not plan.location_changes:
            continue
        option = next(
            (
                option
                for option in choice.options
                if metadata.distance_meters(option.value, plan.location) <= LOCATION_SAME_METERS
            ),
            None,
        )
        if option is None:
            option = Option(
                id=_short_hash(f"{plan.location.x:.6f},{plan.location.y:.6f}"),
                value=plan.location,
                distance=plan.location_distance,
            )
            choice.options.append(option)
        option.sources.append(f"{group.label} ({plan.location_source})")

    if not choice.options:
        return None
    if platform.geom is None and len(choice.options) == 1:
        choice.default = choice.options[0].id
    return choice


def plan_sync(platform: Platform) -> SyncPlan:
    """Work out what syncing a platform with its datasets would change. Nothing is saved."""
    sync = SyncPlan(platform=platform)

    for dataset, timeseries in _timeseries_by_dataset(platform).items():
        try:
            sync.groups.extend(_plan_dataset(platform, dataset, timeseries))
        except (requests.RequestException, ValueError) as e:  # noqa: PERF203
            sync.errors.append(DatasetError(dataset=dataset, message=str(e)))

    sync.fields = _field_choices(platform, sync.groups)
    sync.location = _location_choice(platform, sync.groups)
    return sync


def _apply_platform_choices(
    sync: SyncPlan,
    fields: dict[str, str],
    location: str | None,
) -> tuple[list[str], bool]:
    platform = sync.platform

    fields_updated = []
    for choice in sync.fields:
        option = choice.option(fields.get(choice.name))
        if option is not None:
            setattr(platform, choice.name, option.value)
            fields_updated.append(choice.name)

    option = sync.location.option(location) if sync.location else None
    if option is not None:
        platform.geom = option.value

    platform.save()
    return fields_updated, option is not None


def apply_sync(
    sync: SyncPlan,
    *,
    create: set[tuple[str, str]] | None = None,
    update: set[tuple[str, str]] | None = None,
    fields: dict[str, str] | None = None,
    location: str | None = None,
) -> SyncResult:
    """Save the selected parts of a sync plan.

    `create` and `update` are `(group id, variable)` pairs, `fields` the option id
    chosen for each platform field, and `location` the chosen location option id.
    Anything not chosen is left as it is.
    """
    create = create or set()
    update = update or set()

    created, updated, datasets = [], [], []
    with transaction.atomic():
        for group in sync.groups:
            to_create = [variable for group_id, variable in create if group_id == group.id]
            to_update = [variable for group_id, variable in update if group_id == group.id]
            if not to_create and not to_update:
                continue

            result = apply_import(
                group.plan,
                create=to_create,
                update=to_update,
                platform_fields=[],
                update_location=False,
            )
            created.extend(result.created)
            updated.extend(result.updated)
            if (result.created or result.updated) and result.dataset not in datasets:
                datasets.append(result.dataset)

        fields_updated, location_updated = _apply_platform_choices(sync, fields or {}, location)

    return SyncResult(
        platform=sync.platform,
        created=created,
        updated=updated,
        datasets=datasets,
        fields_updated=fields_updated,
        location_updated=location_updated,
    )
