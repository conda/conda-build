SHELL := /bin/bash -o pipefail -o errexit

env-docs:
	conda create --name conda-build-docs --channel defaults python=3.8 --yes
	conda run --name conda-build-docs pip install -r ./docs/requirements.txt

.PHONY: $(MAKECMDGOALS)
