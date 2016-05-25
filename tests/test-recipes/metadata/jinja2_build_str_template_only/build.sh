# We test the environment variables in a different recipe

# Ensure we are in a git repo
[ -d .git ]
git describe
[ "$(git describe)" = 1.8.1 ]
PYTHONPATH=. python -c "import conda_build; assert conda_build.__version__ == '1.8.1', conda_build.__version__"

# check if GIT_* variables are defined
for i in GIT_DESCRIBE_TAG GIT_DESCRIBE_NUMBER GIT_DESCRIBE_HASH GIT_FULL_HASH
do
  if [ -n "eval $i" ]; then
    eval echo \$$i
  else
    exit 1
  fi
done
