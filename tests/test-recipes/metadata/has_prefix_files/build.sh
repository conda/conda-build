echo $PREFIX > $PREFIX/unlisted-text-prefix
echo /opt/anaconda1anaconda2anaconda3 > $PREFIX/has-prefix
python $RECIPE_DIR/write_binary_has_prefix.py
