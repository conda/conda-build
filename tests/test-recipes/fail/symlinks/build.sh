# file1 exists and file2 doesn't
touch $PREFIX/file1
touch $RECIPE_DIR/file1
touch $SRC_DIR/file1

# This should work but be converted to relative links
ln -s $PREFIX/file1 $PREFIX/good_abs_link_file1
ln -s $PREFIX/file2 $PREFIX/good_abs_link_file2

# Absolute symlinks outside of conda-bld should be left alone
ln -s /usr/bin $PREFIX/good_usr_bin_link

cd $PREFIX

# This should work
ln -s ./file1 $PREFIX/good_relative_link_file1
ln -s ./file2 $PREFIX/good_relative_link_file2

# Relative links without a .
# This should also work
ln -s file1 $PREFIX/good_relative_link_nodot_file1
ln -s file2 $PREFIX/good_relative_link_nodot_file2

ln -s $RECIPE_DIR/file1 $PREFIX/good_outside_link_file1
ln -s $RECIPE_DIR/file2 $PREFIX/good_outside_link_file2

# These should give errors
ln -s $SRC_DIR/file1 $PREFIX/bad_abs_link_src_file1
ln -s $SRC_DIR/file2 $PREFIX/bad_abs_link_src_file2

# Assumes $SRC_DIR is $PREFIX/../conda-bld/work
ln -s ../../conda-bld/work/file1 $PREFIX/bad_relative_link_src_file1
ln -s ../../conda-bld/work/file2 $PREFIX/bad_relative_link_src_file2

# Relative path outside the build prefix that doesn't start with a .
mkdir dir
ln -s dir/../../../conda-bld/work/file1 $PREFIX/bad_relative_outside_nodot_file1
ln -s dir/../../../conda-bld/work/file2 $PREFIX/bad_relative_outside_nodot_file2
