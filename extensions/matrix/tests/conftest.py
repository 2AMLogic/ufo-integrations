"""Collection gates for the matrix surface tests.

The integration test drives a real homeserver, so it is collected only where one is named. CI
never sets the gate: the suite there is unchanged, and the registry job's no-skip rule holds. The
gate and what it expects of the homeserver are documented in `extensions/matrix/README.md`."""

import os

if os.environ.get("MATRIX_INTEGRATION_HOMESERVER") is None:
    collect_ignore = ["test_matrix_integration.py"]
