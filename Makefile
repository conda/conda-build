SHELL := /bin/bash -o pipefail -o errexit

# You can override all of these variables on the command line like so:
# ENV_NAME=dev TMPDIR=$HOME make test
ENV_NAME ?= conda-build
DOC_ENV_NAME ?= conda-build-docs
PYTHON_VERSION ?= 3.8
TMPDIR := $(shell if test -w $(TMPDIR); then echo $(TMPDIR); else echo ./tmp/ ; fi)conda-build-testing

# We want to bypass the shell wrapper function and use the binary directly for conda-run specifically
# See: https://github.com/conda/conda/issues/11174
CONDA := $(shell which conda)

# Setup env for documents
env-docs:
	conda create --name $(DOC_ENV_NAME) --channel defaults python=$(PYTHON_VERSION) --yes
	$(CONDA) run --name $(DOC_ENV_NAME) pip install -r ./docs/requirements.txt

.PHONY: $(MAKECMDGOALS)

.PHONY: setup
setup:
	$(CONDA) create --name $(ENV_NAME) --file tests/requirements.txt --channel defaults python=$(PYTHON_VERSION)

# Runs all tests
.PHONY: test
test: $(TMPDIR)
	$(CONDA) run --no-capture-output -n $(ENV_NAME) python -m pytest tests/ --basetemp $(TMPDIR)

# Run the serial tests
.PHONY: test-serial
test-serial: $(TMPDIR)
	$(CONDA) run --no-capture-output -n $(ENV_NAME) python -m pytest tests/ -m "serial" --basetemp $(TMPDIR)

# Run the not serial tests AKA parallel tests
.PHONY: test-parallel
test-parallel: $(TMPDIR)
	$(CONDA) run --no-capture-output -n $(ENV_NAME) python -m pytest tests/ -m "not serial" --basetemp $(TMPDIR)

$(TMPDIR):
	mkdir -p $(TMPDIR)
