echo %PREFIX% > "%PREFIX%\automatic-prefix"
echo /opt/anaconda1anaconda2anaconda3 > "%PREFIX%\has-prefix"
python "%RECIPE_DIR%\write_binary_has_prefix.py"
python "%RECIPE_DIR%\write_forward_slash_prefix.py"
