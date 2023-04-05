#!/usr/bin/env python
# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import conda_build_test

conda_build_test

print("Test script setup.py")

if __name__ == "__main__":
    from conda_build_test import manual_entry

    manual_entry.main()
