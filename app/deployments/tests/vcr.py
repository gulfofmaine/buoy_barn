from datetime import UTC, datetime

import vcr

my_vcr = vcr.VCR(
    cassette_library_dir="deployments/tests/cassettes/",
    match_on=["method", "scheme", "host", "port", "path"],
    decode_compressed_response=True,
)


# `setup_variables` builds every ERDDAP query URL from `datetime.now(UTC)`, so a test
# replaying a cassette asks for a different time range on every run and slowly drifts away
# from the request that was recorded. Tests that replay the ERDDAP error cassettes freeze
# the clock here instead, so the URL they build is the same today as it will be next year.
#
# Late enough that every `actual_range` baked into those cassettes is more than a week old,
# which is the cutoff `handle_500_time_range_error` retires a timeseries on -- and late
# enough to sit after the last of them was recorded (2021-03-28).
CASSETTE_RECORDED_AT = datetime(2021, 3, 29, tzinfo=UTC)
