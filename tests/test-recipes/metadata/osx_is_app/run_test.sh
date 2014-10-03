test-script-setup.py
test-script-setup.py | grep "Test script setup\.py"
cat $PREFIX/bin/test-script-setup.py | grep "python\.app"

test-script-manual
test-script-manual | grep "Manual entry point"
cat $PREFIX/bin/test-script-manual | grep "python\.app"
