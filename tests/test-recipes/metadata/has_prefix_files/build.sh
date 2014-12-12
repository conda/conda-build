echo $PREFIX > $PREFIX/automatic-prefix
echo /opt/anaconda1anaconda2anaconda3 > $PREFIX/has-anaconda-prefix
echo /installation_prefix_placeholder >> $PREFIX/has-prefix
python $RECIPE_DIR/write_binary_has_prefix.py
