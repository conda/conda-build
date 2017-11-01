# this tests an issue where the prefix folder structure was captured into
# packages, and the later occurrence was being replaced in conda-builds notion,
# but not on disk. It should have only been getting replaced for the first
# instance, to obtain a relative path.

# this test creates a file in such a path, and triggers the behavior
mkdir -p $PREFIX/include/$PREFIX
echo 'weeee' > $PREFIX/include/$PREFIX/test
