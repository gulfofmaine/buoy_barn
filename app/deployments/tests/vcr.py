import vcr

my_vcr = vcr.VCR(
    cassette_library_dir="deployments/tests/cassettes/",
    match_on=["method", "scheme", "host", "port", "path"],
)
