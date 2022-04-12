SHELL := /bin/bash -o pipefail -o errexit

# You can override all of these variables on the command line like so:
# ENV_NAME=dev TMPDIR=$HOME make test
ENV_NAME ?= "conda-build"
DOC_ENV_NAME ?= "conda-build-docs"
PYTHON_VERSION ?= 3.8

TMPDIR := $(shell if test -w $(TMPDIR); then echo $(TMPDIR); else echo "./tmp"; fi)
# Setup env for documents
env-docs:
	conda create --name $(DOC_ENV_NAME) --channel defaults python=$(PYTHON_VERSION) --yes
	conda run --name $(DOC_ENV_NAME) pip install -r ./docs/requirements.txt

.PHONY: $(MAKECMDGOALS)

# Runs all tests
.PHONY: test
test: ../conda_build_test_recipe $(TMPDIR)
	conda run --live-stream -n $(ENV_NAME) pytest tests/ --basetemp $(TMPDIR)

# Run the serial tests
.PHONY: test-serial
test-serial: ../conda_build_test_recipe $(TMPDIR)
	conda run --live-stream -n $(ENV_NAME) pytest tests/ -m "serial" --basetemp $(TMPDIR)

# Run the not serial tests
.PHONY: test-not-serial
test-not-serial: ../conda_build_test_recipe $(TMPDIR)
	conda run --live-stream -n $(ENV_NAME) pytest tests/ -m "not serial" --basetemp $(TMPDIR)

# Checkout the required test recipes
# Requires write access to the directory above this
../conda_build_test_recipe:
	git clone https://github.com/conda/conda_build_test_recipe ../conda_build_test_recipe


$(TMPDIR):
	mkdir -p $(TMPDIR)
