#!/bin/bash

# This script assumes we are running in a Miniconda container where:
# - /opt/conda is the Miniconda or Miniforge installation directory
# - https://github.com/conda/conda is mounted at /workspaces/conda
# - https://github.com/conda/conda-libmamba-solver is mounted at
#   /workspaces/conda-libmamba-solver
# - https://github.com/mamba-org/mamba is (optionally) mounted at
#   /workspaces/mamba

set -euo pipefail

BASE_CONDA=${BASE_CONDA:-/opt/conda}
SRC_CONDA_BUILD=${SRC_CONDA_BUILD:-/workspaces/conda-build}

echo "Installing conda-build in dev mode..."
"$BASE_CONDA/bin/python" -m pip install -e "$SRC_CONDA_BUILD" --no-deps

set -x
conda list -p "$BASE_CONDA"
conda info
conda config --show-sources
set +x

