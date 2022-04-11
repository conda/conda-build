SHELL := /bin/bash -o pipefail -o errexit
TMPDIR := $(shell mktemp -d)
ENV := $(shell conda env list | awk '/conda-build/ { print $2 }')

env-docs:
	conda create --name conda-build-docs --channel defaults python=3.8 --yes
	conda run --name conda-build-docs pip install -r ./docs/requirements.txt

.PHONY: $(MAKECMDGOALS)

.PHONY: test
test: test-serial test-not-serial

.PHONY: test-serial
test-serial: ../conda_build_test_recipe $(ENV)
	conda run --live-stream -n conda-build pytest tests/ -m "serial" --basetemp $$TMPDIR

.PHONY: test-not-serial
test-not-serial: ../conda_build_test_recipe $(ENV)
	conda run --live-stream -n conda-build pytest tests/ -m "not serial" --basetemp $$TMPDIR

../conda_build_test_recipe:
	git clone https://github.com/conda/conda_build_test_recipe ../conda_build_test_recipe

# Creates the conda-build environment if it doesn't yet exist
$(ENV):
	conda create --name conda-build --file tests/requirements.txt --channel defaults
