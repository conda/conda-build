set -x

cd $PREFIX
cat binary-has-prefix
cat binary-has-prefix | grep $PREFIX

cat binary-has-prefix-ignored
cat binary-has-prefix-ignored | grep --invert-match $PREFIX
