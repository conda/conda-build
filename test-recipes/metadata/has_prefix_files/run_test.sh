cd $PREFIX
cat automatic-prefix
cat automatic-prefix | grep $PREFIX
cat has-prefix
cat has-prefix | grep $PREFIX
cat has-prefix | grep -v /opt/anaconda1anaconda2anaconda3
cat has-prefix-not-listed
cat has-prefix-not-listed | grep -v $PREFIX
cat has-prefix-not-listed | grep /opt/anaconda1anaconda2anaconda3
