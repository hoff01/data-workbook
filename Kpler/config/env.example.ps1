$env:KPLER_EMAIL = ""
$env:KPLER_PASSWORD = ""

# Dynamic date controls.
$env:KPLER_START_DATE = "2018-01-01"
$env:KPLER_FORWARD_DAYS = "45"
# Optional hard override:
# $env:KPLER_END_DATE = "2026-07-01"

# Runtime tuning.
$env:KPLER_CONCURRENCY = "2"
$env:KPLER_RETRY_COUNT = "3"
$env:KPLER_RETRY_BACKOFF_SECONDS = "10"
$env:KPLER_VERIFY_TLS = "true"
