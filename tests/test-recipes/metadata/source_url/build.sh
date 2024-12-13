cd constructor-tar-gz
# Not sure how versioneer comes up with this version
PYTHONPATH=. python -c "import constructor; assert constructor.__version__ == '3.0.0'"
