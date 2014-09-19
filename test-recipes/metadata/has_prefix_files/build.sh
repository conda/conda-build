echo $PREFIX > $PREFIX/automatic-prefix
echo /opt/anaconda1anaconda2anaconda3 > $PREFIX/has-prefix
$PYTHON write_binary_has_prefix.py
