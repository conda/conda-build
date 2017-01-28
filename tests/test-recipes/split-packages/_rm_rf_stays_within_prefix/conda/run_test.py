import os
import sys

if sys.platform != 'win32':
    assert os.path.isfile(os.path.join(os.getenv("PREFIX"), 'bin', 'lsfm'))
else:
    assert os.path.isfile(os.path.join(os.getenv("PREFIX"), 'Scripts', 'lsfm.exe'))
