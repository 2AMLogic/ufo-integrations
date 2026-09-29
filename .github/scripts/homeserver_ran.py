import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# This job exists to run the tests the gate holds back everywhere else, so a report with
# nothing in it is this job's own failure: an unset env var, a module that would not
# import, and a homeserver that came up too late all read as a green suite otherwise.
cases = list(ET.parse(sys.argv[1]).iter("testcase"))
skipped = [f"{c.get('classname')}::{c.get('name')}" for c in cases if c.find("skipped") is not None]
if not cases:
    print("::error::no test ran, so the gate held this suite back from the job that sets it")
    sys.exit(1)
if skipped:
    print("::error::this job names a homeserver and installs the extra, so no test may skip")
    print("\n".join(skipped))
    sys.exit(1)

# Naming the directory is not enough on its own: a module this job exists for could stop
# being collected — renamed, ignored by a conftest edit, failing to import behind a guard
# — and the rest of the suite would keep this step green while the homeserver went
# unexercised. Each gated module is asked for by name, from the same directory the gate
# reads, by the `*_integration.py` naming convention rather than by parsing conftest's
# ignore list directly — the two agree today but are not the same source.
ran = {c.get("classname", "").rsplit(".", 1)[-1] for c in cases}
gated = sorted(p.stem for p in Path(sys.argv[2]).glob("*_integration.py"))
missing = [name for name in gated if name not in ran]
if not gated:
    print("::error::no gated module found, so this job is checking an empty rule")
    sys.exit(1)
if missing:
    print("::error::a module this job exists for contributed no test")
    print("\n".join(missing))
    sys.exit(1)
print(f"{len(cases)} tests ran against the homeserver, none skipped")
print(f"gated modules that ran: {', '.join(gated)}")
