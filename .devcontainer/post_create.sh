#!/bin/bash

set -euo pipefail

BASE_CONDA=${BASE_CONDA:-/opt/conda}
SRC_CONDA_BUILD=${SRC_CONDA_BUILD:-/workspaces/conda-build}

if which apt-get > /dev/null; then
    HERE=$(dirname $0)
    echo "Installing system dependencies"
    apt-get update
    DEBIAN_FRONTEND=noninteractive xargs -a "$HERE/apt-deps.txt" apt-get install -y
fi

# Clear history to avoid unneeded conflicts
echo "Clearing base history..."
echo '' > "$BASE_CONDA/conda-meta/history"

echo "Installing dev dependencies"
"$BASE_CONDA/bin/conda" install \
    -n base \
    --yes \
    --quiet \
    --file "$SRC_CONDA_BUILD/tests/requirements.txt" \
    --file "$SRC_CONDA_BUILD/tests/requirements-Linux.txt" \
    --file "$SRC_CONDA_BUILD/tests/requirements-ci.txt" \
    "conda>=23.7.0"
