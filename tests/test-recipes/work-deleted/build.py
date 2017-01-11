import os

PREFIX = os.environ["PREFIX"]
SRC_DIR = os.environ["SRC_DIR"]

with open(os.path.join(PREFIX, 'conda-build-test'), 'w') as f:
    f.write(SRC_DIR)
