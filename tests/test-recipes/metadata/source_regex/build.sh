# We test the environment variables in a different recipe

# Ensure we are in a git repo
[ -d .git ]
git describe
[ "$(git describe)" = 1.21.0 ]
# This looks weird, but it reflects accurately the meta.yaml in conda_build_test_recipe at 1.21.0 tag
echo "\$PKG_VERSION = $PKG_VERSION"
[ "${PKG_VERSION}" = 1.20.2 ]
