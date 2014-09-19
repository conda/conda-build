echo $PREFIX > $PREFIX/automatic-prefix
echo /opt/anaconda1anaconda2anaconda3 > $PREFIX/has-prefix
python $RECIPE_DIR/test-recipes/metadata/has_prefix_files/write_binary_has_prefix.py
