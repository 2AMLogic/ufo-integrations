import sys
from importlib.util import find_spec

if find_spec("vodozemac") is not None:
    print("::error::vodozemac is installed, so this is not the lane without the extra")
    sys.exit(1)
if find_spec("cryptography") is None:
    print("::error::cryptography is absent, so ufo is not installed and neither is the lane")
    sys.exit(1)
print("vodozemac absent, cryptography present: the extra is what is missing, and only it")
