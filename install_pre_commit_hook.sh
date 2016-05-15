#!/bin/bash
cd "${0%/*}"
ln -s $(pwd)/git_hooks/pre-commit .git/hooks/pre-commit
