if not exist trunk exit 1
cd trunk
svn info
if errorlevel 1 exit 1
for /f "delims=" %%i in ('svn info | grep "Revision"') do set svnrev=%%i
if not svnrev=="Revision: 1157" exit 1
