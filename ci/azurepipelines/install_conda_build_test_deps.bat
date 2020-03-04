if not exist %TEMP%\Miniconda3-latest-Windows-x86_64.exe (
  where /q wget
  if ERRORLEVEL 1 (
    :: I wanted to use C:\msys32 here (as I do in general to avoid ABI issues with our m2- packages), but that
    :: ended up with a Miniconda installer with incorrect permissions. Very weird.
    C:\msys64\usr\bin\curl.exe -SLO https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe
    if ERRORLEVEL 1 exit /b 1
    move Miniconda3-latest-Windows-x86_64.exe %TEMP%
    :: echo Please install wget (or fix this script to use other methods to download the Miniconda Windows installer)
    :: exit /b 1
    if ERRORLEVEL 1 exit /b 1
  ) else (
    :: wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe
    C:\msys64\usr\bin\curl.exe -SLO https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe
    if ERRORLEVEL 1 exit /b 1
    move Miniconda3-latest-Windows-x86_64.exe %TEMP%
    if ERRORLEVEL 1 exit /b 1
  )
)
start /wait "" %TEMP%\Miniconda3-latest-Windows-x86_64.exe /InstallationType=JustMe /S /D=%1
if ERRORLEVEL 1 exit /b 1
call "%1\condabin\conda.bat" init
doskey conda="call %1\condabin\conda.bat" $*
doskey /macros
where conda
call conda info -a

set _PKGS=cytoolz pytest pytest-azurepipelines pytest-cov pytest-forked pytest-xdist
set _PKGS=%_PKGS% conda-forge::pytest-replay conda-forge::pytest-rerunfailures
set _PKGS=%_PKGS% anaconda-client git requests filelock contextlib2 jinja2
set _PKGS=%_PKGS% ripgrep pyflakes beautifulsoup4 chardet pycrypto glob2 psutil pytz tqdm
set _PKGS=%_PKGS% conda-package-handling py-lief python-libarchive-c perl
set _PKGS=%_PKGS% pip numpy mock pytest-mock pkginfo
set _PKGS=%_PKGS% m2-patch m2-filesystem flake8

call conda install -y --show-channel-urls %_PKGS%

if not exist ..\conda_build_test_recipe (
  pushd ..
    git clone https://github.com/conda/conda_build_test_recipe
  popd
}
