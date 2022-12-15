#!/usr/bin/env python
import conda_build_test
conda_build_test

print("Test script setup.py")

if __name__ == "__main__":
    from conda_build_test import manual_entry
    manual_entry.main()
