set PYTHONPATH=.
python -c "import conda_build; assert conda_build.__version__ == 'tag: 1.8.1'"
if errorlevel 1 exit 1
