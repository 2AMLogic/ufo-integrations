"""Collection gates for the matrix surface tests.

The integration tests drive a real homeserver, so they are collected only where one is named, and
one env var names it for all of them. Every job that leaves the gate unset collects what it always
did, and the registry job's no-skip rule holds. The gate and what
it expects of the homeserver are documented in `extensions/matrix/README.md`."""

import os

if os.environ.get("MATRIX_INTEGRATION_HOMESERVER") is None:
    collect_ignore = ["test_matrix_integration.py", "test_matrix_crypto_integration.py"]
