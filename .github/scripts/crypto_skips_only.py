import sys
import xml.etree.ElementTree as ET

# A module-level `pytest.importorskip` skips collection, and junitxml reports that as
# `classname=''` with the module's dotted path in `name` — the opposite placement from a
# skipped test function, which names its module in `classname`. Reading the pair as one
# string is what lets this gate bless the one skip it exists for; matching `classname`
# alone called that skip a stray and turned the step red.
cases = list(ET.parse(sys.argv[1]).iter("testcase"))
named = [
    f"{c.get('classname', '')}::{c.get('name', '')}"
    for c in cases
    if c.find("skipped") is not None
]
stray = [where for where in named if "test_matrix_crypto" not in where]
if stray:
    print("::error::the crypto extra's absence may silence only the crypto tests")
    print("\n".join(stray))
    sys.exit(1)
if not named:
    print("::error::the crypto tests did not skip, so the extra was installed after all")
    sys.exit(1)
print(f"{len(cases)} tests ran, {len(named)} skipped, all of test_matrix_crypto:")
print("\n".join(named))
