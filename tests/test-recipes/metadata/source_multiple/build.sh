# Check that second source was fetched properly
[ -d second-source ]
cd second-source
[ -d .git ]
git describe
[ "$(git describe)" = 1.20.2 ]
cd -

# Check if GIT_* variables are defined
# Note that these describe the first source, not the second one.
for i in GIT_DESCRIBE_TAG GIT_DESCRIBE_NUMBER GIT_DESCRIBE_HASH GIT_FULL_HASH
do
  if [ -n "eval $i" ]; then
    eval echo \$$i
  else
    exit 1
  fi
done
