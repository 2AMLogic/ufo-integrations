import sys
import xml.etree.ElementTree as ET

cases = list(ET.parse(sys.argv[1]).iter("testcase"))
skipped = [f"{c.get('classname')}::{c.get('name')}" for c in cases if c.find("skipped") is not None]
registry = [
    c for c in cases if "test_registry" in c.get("classname", "") and c.find("skipped") is None
]
if skipped:
    print("::error::this job runs against ufo, so no test may skip")
    print("\n".join(skipped))
    sys.exit(1)
if not registry:
    print("::error::the registry test did not run")
    sys.exit(1)
print(f"{len(cases)} tests ran, {len(registry)} of them against the registry, none skipped")
