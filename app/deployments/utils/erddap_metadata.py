"""Read what Buoy Barn needs to know about a dataset from its ERDDAP metadata.

Everything here works from the `info/<dataset_id>/index.csv` table, parsed once into a
`DatasetInfo`. Apart from `fetch_dataset_info` and the station lookup in
`platform_location` (which talk to ERDDAP), the functions are pure, so the attribute
conventions they follow can be tested from small handwritten tables:

- QARTOD: a data variable lists its QC flag variables in `ancillary_variables`, each with
  `flag_values` and `flag_meanings`. Rollup flags (`standard_name = aggregate_quality_flag`)
  are often not listed there, so they are found by scanning the whole dataset instead.
- Tidal datums: a `tidal_datum_offsets_meters` variable attribute holding a JSON object
  such as `{"mhhw": 1.469, "mllw": -1.573}`.
"""

import io
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pandas as pd
import requests
from django.contrib.gis.geos import Point

from ..models import DataType, ErddapServer, Platform, TimeSeries

GLOBAL = "NC_GLOBAL"

COORDINATE_VARIABLES = {"time", "latitude", "longitude", "depth", "lat", "lon", "z"}
NON_DATA_VARIABLES = {
    "station",
    "mooring_site_desc",
    "time_modified",
    "time_created",
    "water_depth",
    "crs",
}

AGGREGATE_FLAG_STANDARD_NAME = "aggregate_quality_flag"
ACCEPTABLE_FLAG_MEANINGS = {"pass", "good", "quality_good", "not_evaluated"}

DATUM_ATTRIBUTE = "tidal_datum_offsets_meters"

# Constraints that select a single station out of a multi-station dataset.
STATION_CONSTRAINT_KEYS = ("station=", "stationID=", "station_id=", "platform=", "platform_id=")

NUMERIC_TYPES = {"byte", "ubyte", "short", "ushort", "int", "uint", "long", "ulong"}
FLOAT_TYPES = {"float", "double"}


@dataclass
class DatasetInfo:
    dataset_id: str
    globals: dict = field(default_factory=dict)
    variables: dict[str, dict] = field(default_factory=dict)
    # ERDDAP's data type for each variable, such as "float" or "String"
    types: dict[str, str] = field(default_factory=dict)

    def var_attr(self, variable: str, attribute: str, default=None):
        return self.variables.get(variable, {}).get(attribute, default)


def _cast(value: str, data_type: str):
    """Cast an ERDDAP info value, splitting comma separated numeric lists."""
    data_type = (data_type or "").lower()
    if data_type in NUMERIC_TYPES or data_type in FLOAT_TYPES:
        cast = int if data_type in NUMERIC_TYPES else float
        parts = [part.strip() for part in value.split(",")]
        try:
            values = [cast(part) for part in parts if part]
        except ValueError:
            return value
        if len(values) == 1:
            return values[0]
        return values
    return value


def parse_info_csv(dataset_id: str, csv_text: str) -> DatasetInfo:
    """Parse the CSV form of ERDDAP's `info` page"""
    df = pd.read_csv(io.StringIO(csv_text), dtype=str, keep_default_na=False)
    info = DatasetInfo(dataset_id=dataset_id)

    for row in df.itertuples(index=False):
        row_type, variable, attribute, data_type, value = row[:5]
        if row_type == "variable":
            info.variables.setdefault(variable, {})
            info.types[variable] = data_type
        elif row_type == "attribute":
            target = info.globals if variable == GLOBAL else info.variables.setdefault(variable, {})
            target[attribute] = _cast(value, data_type)

    return info


def fetch_dataset_info(server: ErddapServer, dataset_id: str) -> DatasetInfo:
    """Load a dataset's metadata from its ERDDAP server"""
    url = server.connection().get_info_url(dataset_id, response="csv")
    response = requests.get(url, timeout=server.request_timeout_seconds)
    response.raise_for_status()
    return parse_info_csv(dataset_id, response.text)


def convert_time(time: str) -> datetime:
    """Convert's from ERDDAP time style to python"""
    return datetime.fromisoformat(time.replace("Z", ""))


def time_range(info: DatasetInfo) -> tuple[datetime | None, datetime | None]:
    """Start and end of the dataset.

    The end is left as None when the dataset has updated within the last day, as that
    marks a timeseries that should still be refreshed.
    """
    start = info.globals.get("time_coverage_start")
    end = info.globals.get("time_coverage_end")

    start_time = convert_time(start).replace(tzinfo=UTC) if start else None
    end_time = convert_time(end).replace(tzinfo=UTC) if end else None

    if end_time and end_time > datetime.now(UTC) - timedelta(hours=24):
        end_time = None

    return start_time, end_time


def _single_value(value) -> float | None:
    """The value of a number, or of a range that starts and ends at the same value"""
    if isinstance(value, int | float):
        return float(value)
    numbers = isinstance(value, list) and value and all(isinstance(v, int | float) for v in value)
    if numbers and math.isclose(min(value), max(value)):
        return float(value[0])
    return None


def _positive_down(value: float | None, positive: str | None) -> float | None:
    if value is None:
        return None
    return -value if str(positive or "").lower() == "up" else value


def _depth_variable(info: DatasetInfo) -> str | None:
    if "depth" in info.variables:
        return "depth"
    return next(
        (name for name, attrs in info.variables.items() if attrs.get("standard_name") == "depth"),
        None,
    )


def variable_depth(info: DatasetInfo, variable: str) -> float | None:
    """The single depth (meters, positive down) a variable is measured at, if there is one.

    From the variable's `sensor_depth` attribute, a depth variable whose `actual_range`
    is a single value, or the dataset's `geospatial_vertical_min/max` when they are equal.
    Datasets with several depths return None, those need a `depth=` constraint instead.
    """
    sensor_depth = _single_value(info.var_attr(variable, "sensor_depth"))
    if sensor_depth is not None:
        return sensor_depth

    depth_variable = _depth_variable(info)
    if depth_variable:
        depth = _single_value(info.var_attr(depth_variable, "actual_range"))
        if depth is not None:
            return _positive_down(depth, info.var_attr(depth_variable, "positive"))

    vertical = [info.globals.get("geospatial_vertical_min"), info.globals.get("geospatial_vertical_max")]
    depth = _single_value(vertical) if all(v is not None for v in vertical) else None
    return _positive_down(depth, info.globals.get("geospatial_vertical_positive"))


def station_constraint(constraints: dict | None) -> tuple[str, str] | None:
    for key in STATION_CONSTRAINT_KEYS:
        if constraints and key in constraints:
            return key, constraints[key]
    return None


def _station_location(server: ErddapServer, dataset_id: str, constraints: dict) -> Point | None:
    e = server.connection()
    url = e.get_download_url(
        dataset_id=dataset_id,
        protocol="tabledap",
        response="csv",
        variables=["latitude", "longitude"],
        constraints=constraints,
        distinct=True,
    )
    response = requests.get(url, timeout=server.request_timeout_seconds)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text), skiprows=[1])
    df = df.dropna()
    if df.empty:
        return None
    return Point(float(df["longitude"].mean()), float(df["latitude"].mean()), srid=4326)


def platform_location(
    info: DatasetInfo,
    server: ErddapServer | None = None,
    constraints: dict | None = None,
) -> tuple[Point | None, str]:
    """Where the platform is, and which metadata it came from"""
    for lat_name, lon_name in (("latitude", "longitude"), ("site_latitude", "site_longitude")):
        lat = info.globals.get(lat_name)
        lon = info.globals.get(lon_name)
        if isinstance(lat, float | int) and isinstance(lon, float | int):
            return Point(float(lon), float(lat), srid=4326), f"{lat_name}/{lon_name} attributes"

    if server is not None and station_constraint(constraints):
        try:
            point = _station_location(server, info.dataset_id, constraints)
        except (requests.RequestException, KeyError, ValueError):
            point = None
        if point:
            return point, "station position in data"

    bounds = [
        info.globals.get(name)
        for name in (
            "geospatial_lat_min",
            "geospatial_lat_max",
            "geospatial_lon_min",
            "geospatial_lon_max",
        )
    ]
    if all(isinstance(bound, float | int) for bound in bounds):
        lat_min, lat_max, lon_min, lon_max = bounds
        return (
            Point((lon_min + lon_max) / 2, (lat_min + lat_max) / 2, srid=4326),
            "middle of geospatial bounds",
        )

    return None, ""


def distance_meters(a: Point, b: Point) -> float:
    """Great circle distance between two lon/lat points"""
    radius = 6_371_000
    lon1, lat1, lon2, lat2 = map(math.radians, (a.x, a.y, b.x, b.y))
    hav = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(hav))


def _standard_names(info: DatasetInfo) -> list[str]:
    return [str(attrs.get("standard_name", "")) for attrs in info.variables.values()]


def platform_defaults(info: DatasetInfo) -> dict:
    """Platform fields that can be filled in from global attributes"""
    defaults = {}

    station_name = (
        info.globals.get("platform_name") or info.globals.get("long_name") or info.globals.get("title")
    )
    if station_name:
        defaults["station_name"] = str(station_name)[:100]

    description = info.globals.get("mooring_site_desc") or info.globals.get("summary")
    if description:
        defaults["mooring_site_desc"] = str(description)

    ndbc_site_id = info.globals.get("ndbc_site_id") or info.globals.get("wmo_platform_code")
    if ndbc_site_id:
        defaults["ndbc_site_id"] = str(ndbc_site_id)[:100]

    if any(name.startswith("sea_surface_height") for name in _standard_names(info)):
        defaults["platform_type"] = Platform.PlatformTypes.TIDE_STATION

    return defaults


def _ancillary(info: DatasetInfo, variable: str) -> list[str]:
    return str(info.var_attr(variable, "ancillary_variables", "")).split()


def is_flag_variable(info: DatasetInfo, variable: str) -> bool:
    attrs = info.variables.get(variable, {})
    standard_name = str(attrs.get("standard_name", ""))
    return (
        "flag_values" in attrs
        or "flag_meanings" in attrs
        or standard_name.endswith("quality_flag")
        or standard_name.endswith("data_quality")
    )


QC_NAME = re.compile(r"(^|_)(qc|qartod)(_|$)")


def is_numeric(info: DatasetInfo, variable: str) -> bool:
    data_type = info.types.get(variable, "").lower()
    return data_type in NUMERIC_TYPES or data_type in FLOAT_TYPES


def is_quality_flag(info: DatasetInfo, variable: str) -> bool:
    """A numeric QC flag that values can be constrained on.

    Excludes other flag variables (such as a `data_source` record) and string arrays of
    individual test results, which can't be compared to a single flag value.
    """
    if not is_flag_variable(info, variable) or not is_numeric(info, variable):
        return False
    attrs = info.variables[variable]
    return (
        attrs.get("intent") == "data_quality"
        or "quality" in str(attrs.get("standard_name", ""))
        or QC_NAME.search(variable) is not None
    )


def _referenced(info: DatasetInfo) -> set[str]:
    """Variables other variables point to as ancillary data, coordinates or instruments"""
    referenced = set()
    for attrs in info.variables.values():
        for attribute in ("ancillary_variables", "coordinates", "instrument", "grid_mapping"):
            referenced.update(str(attrs.get(attribute, "")).split())
    return referenced


def data_variables(info: DatasetInfo) -> list[str]:
    """Variables that could become timeseries"""
    excluded = set(COORDINATE_VARIABLES) | NON_DATA_VARIABLES | _referenced(info)
    for attr in ("cdm_timeseries_variables", "cdm_profile_variables", "cdm_trajectory_variables"):
        excluded.update(name.strip() for name in str(info.globals.get(attr, "")).split(","))

    return [
        variable
        for variable, attrs in info.variables.items()
        if variable not in excluded
        and is_numeric(info, variable)
        and not is_flag_variable(info, variable)
        and attrs.get("cf_role") is None
        and str(attrs.get("standard_name", "")) not in COORDINATE_VARIABLES
    ]


def aggregate_flags(info: DatasetInfo) -> tuple[dict[str, list[str]], list[str]]:
    """Assign rollup flag variables to the data variables they describe.

    Returns the rollups for each data variable, and warnings for rollups that could not
    be assigned.
    """
    variables = data_variables(info)
    aggregates = [
        name
        for name, attrs in info.variables.items()
        if attrs.get("standard_name") == AGGREGATE_FLAG_STANDARD_NAME
    ]

    assigned: dict[str, list[str]] = {variable: [] for variable in variables}
    unclaimed = []

    for aggregate in aggregates:
        listed_by = [variable for variable in variables if aggregate in _ancillary(info, variable)]
        if listed_by:
            for variable in listed_by:
                assigned[variable].append(aggregate)
            continue

        prefixed = [variable for variable in variables if aggregate.startswith(f"{variable}_")]
        if prefixed:
            assigned[max(prefixed, key=len)].append(aggregate)
            continue

        unclaimed.append(aggregate)

    warnings = []
    if len(unclaimed) == 1:
        for variable in variables:
            assigned[variable].append(unclaimed[0])
    elif unclaimed:
        warnings.append(
            "Unable to tell which variables these aggregate quality flags apply to: "
            + ", ".join(unclaimed),
        )

    return assigned, warnings


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    return [value]


def flag_constraint(info: DatasetInfo, flag_variable: str) -> tuple[dict, str | None]:
    """The ERDDAP constraint that keeps only acceptable values of a flag variable"""
    attrs = info.variables.get(flag_variable, {})
    values = attrs.get("flag_values")
    meanings = str(attrs.get("flag_meanings", "")).split()

    if values is None or not meanings:
        return {}, f"{flag_variable} does not have flag_values and flag_meanings"

    values = _as_list(values)
    if len(values) != len(meanings):
        return {}, f"{flag_variable} has a different number of flag_values and flag_meanings"

    flags = sorted(zip(values, meanings, strict=True))
    acceptable = [value for value, meaning in flags if meaning.lower() in ACCEPTABLE_FLAG_MEANINGS]

    if not acceptable:
        return {}, f"{flag_variable} has no flag meaning pass or good"
    if len(acceptable) == 1:
        return {f"{flag_variable}=": acceptable[0]}, None

    lowest = [value for value, _ in flags[: len(acceptable)]]
    if lowest == acceptable:
        return {f"{flag_variable}<=": acceptable[-1]}, None

    return {}, f"{flag_variable} acceptable flags {acceptable} cannot be expressed as one constraint"


def qartod_constraints(
    info: DatasetInfo,
    variable: str,
    aggregates: dict[str, list[str]] | None = None,
) -> tuple[dict, list[str]]:
    """Constraints that filter a variable to data that passed QC"""
    if aggregates is None:
        aggregates, _ = aggregate_flags(info)

    flag_variables = [
        name
        for name in _ancillary(info, variable)
        if name in info.variables and is_quality_flag(info, name)
    ]
    for aggregate in aggregates.get(variable, []):
        if aggregate not in flag_variables:
            flag_variables.append(aggregate)

    constraints = {}
    warnings = []
    for flag_variable in flag_variables:
        constraint, warning = flag_constraint(info, flag_variable)
        constraints.update(constraint)
        if warning:
            warnings.append(warning)

    if not flag_variables:
        warnings.append("No QC flag variables found")

    return constraints, warnings


def tidal_datums(info: DatasetInfo, variable: str) -> tuple[dict[str, float], list[str]]:
    """Tidal datum offsets from the `tidal_datum_offsets_meters` attribute"""
    raw = info.var_attr(variable, DATUM_ATTRIBUTE)
    if raw is None:
        return {}, []

    try:
        offsets = json.loads(raw)
    except (TypeError, ValueError):
        return {}, [f"Unable to read {DATUM_ATTRIBUTE}: {raw!r}"]
    if not isinstance(offsets, dict):
        return {}, [f"{DATUM_ATTRIBUTE} is not a JSON object: {raw!r}"]

    datums = {}
    warnings = []
    for key, value in offsets.items():
        field_name = f"datum_{key.lower()}_meters"
        if field_name not in TimeSeries.DATUMS:
            warnings.append(f"Unknown tidal datum {key!r}")
            continue
        try:
            datums[field_name] = float(value)
        except (TypeError, ValueError):
            warnings.append(f"Tidal datum {key!r} is not a number: {value!r}")

    return datums, warnings


def match_data_type(attrs: dict) -> tuple[DataType | None, str | None]:
    """Find an existing DataType for a variable. DataTypes are never created here."""
    for attribute in ("standard_name", "long_name", "short_name"):
        value = attrs.get(attribute)
        if not value:
            continue
        candidates = list(DataType.objects.filter(**{attribute: value}))
        if not candidates:
            continue
        # The same name can be stored with different units, prefer the matching one
        same_units = [candidate for candidate in candidates if candidate.units == attrs.get("units")]
        return (same_units or candidates)[0], None

    return None, (
        "Unable to import: no matching DataType for "
        f"standard_name={attrs.get('standard_name')!r}, long_name={attrs.get('long_name')!r}, "
        f"short_name={attrs.get('short_name')!r}"
    )
