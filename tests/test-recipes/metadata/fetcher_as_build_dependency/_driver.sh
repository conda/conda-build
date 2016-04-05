#!/bin/bash -e

RECIPE_DIR="$(dirname "${BASH_SOURCE[0]}")"

# Create a temp dir and ensure cleanup
BASE=$(mktemp -d -t XXXXX)
trap "{ rm -rf "$BASE" "$RECIPE_DIR/meta.yaml"; }" EXIT

# Extract the local SVN repo and generate meta.yaml
tar xf "$RECIPE_DIR/_svn_repo.tar.gz" -C "$BASE"
cat > "$RECIPE_DIR/meta.yaml" <<-EOF
	package:
	  name: test-fetcher-as-build-dependency
	  version: 1.0

	source:
	  svn_url: file://$BASE/_svn_repo/dummy
	  svn_rev: 1

	requirements:
	  build:
	    # To test the conda_build version
	    - svn
EOF

# Create a dummy svn executable and add it to the PATH
# to hide any svn that may already be on the system
export TMPBINDIR="$BASE/bin"
mkdir -p "$TMPBINDIR"
cat > "$TMPBINDIR/svn" <<-EOF
	#!/bin/bash
	exec 1>&2
	echo
	echo " ******* You've reached the dummy svn. It's likely there's a bug in conda  *******"
	echo " ******* that makes it not add the _build/bin directory onto the PATH      *******"
	echo " ******* before running the source fetcher                                 *******"
	echo
	exit -1
EOF
chmod +x "$TMPBINDIR/svn"
export PATH="$TMPBINDIR:$PATH"

# Execute the build command
"$@"
