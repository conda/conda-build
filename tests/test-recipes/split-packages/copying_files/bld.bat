echo "weee" > %PREFIX%\subpackage_file1
mkdir %PREFIX%\somedir
echo "weee" > %PREFIX%\somedir\subpackage_file1
echo "weee" > %PREFIX%\subpackage_file1.ext
echo "weee" > %PREFIX%\subpackage_file2.ext
echo "weee" > %PREFIX%\subpackage_file3.ext

echo "weee" > %PREFIX%\subpackage_include_exclude1
mkdir %PREFIX%\anotherdir
echo "weee" > %PREFIX%\anotherdir\subpackage_include_exclude1
echo "weee" > %PREFIX%\subpackage_include_exclude1.wav
echo "weee" > %PREFIX%\subpackage_include_exclude2.wav
echo "weee" > %PREFIX%\subpackage_include_exclude3.wav
mkdir %PREFIX%\Library\bin
echo "weee" > %PREFIX%\Library\bin\dav1d.fake
