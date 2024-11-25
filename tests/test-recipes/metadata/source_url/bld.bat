cd constructor-tar-gz
set PYTHONPATH=.
python -c "import constructor; assert constructor.__version__ == '3.0.0'"
if errorlevel 1 exit 1
