import sys
# import setuptools should work
import setuptools
try:
    # import pip should not.  The exception is what we want to see.
    import pip
except ImportError:
    sys.exit(0)
sys.exit(1)
