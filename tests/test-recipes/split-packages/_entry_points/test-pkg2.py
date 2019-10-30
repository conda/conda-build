import os
import subprocess
import sys
import pkg2

pkg2.main()
bindir = "Scripts" if sys.platform == "win32" else "bin"
print("attempting to call ", os.path.join(os.getenv("PREFIX"), bindir, "pkg2"))
subprocess.check_call([os.path.join(os.getenv("PREFIX"), bindir, "pkg2")])
