# Paste only the Kpler API v2 key value after "Basic ".
$env:KPLER_API_KEY = ""
# Or set the complete Authorization header value instead:
# $env:KPLER_API_V2_BASIC_AUTH = "Basic ..."
# Optional non-production override; the default is https://api.kpler.com/v2/cargo.
# $env:KPLER_API_BASE_URL = ""

# Dynamic date controls.
$env:KPLER_START_DATE = "2018-01-01"
$env:KPLER_FORWARD_DAYS = "45"
# Optional hard override:
# $env:KPLER_END_DATE = "2026-07-01"

# Runtime tuning.
$env:KPLER_CONCURRENCY = "2"
$env:KPLER_RETRY_COUNT = "3"
$env:KPLER_RETRY_BACKOFF_SECONDS = "2"
$env:KPLER_VERIFY_TLS = "true"
$env:KPLER_PULL_FAMILIES = "balance_guides"
$env:KPLER_PULL_NAMES = ""
$env:KPLER_PULL_ROUTE_GROUPS = ""
$env:KPLER_USER_AGENT = "US-Balances-Kpler-Pull/2.0"
