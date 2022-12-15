# SPDX-FileCopyrightText: © 2012 Continuum Analytics, Inc. <http://continuum.io>
# SPDX-FileCopyrightText: © 2017 Anaconda, Inc. <https://www.anaconda.com>
# SPDX-License-Identifier: BSD-3-Clause
def main():
    import argparse

    # Just picks them up from `sys.argv`.
    parser = argparse.ArgumentParser(
        description="Basic parser."
    )
    parser.parse_args()

    print("Manual entry point")
