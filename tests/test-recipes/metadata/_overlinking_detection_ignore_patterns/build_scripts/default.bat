@echo on
echo int main() { return 0; }>main.c
cl -c -EHsc -GR -Zc:forScope -Zc:wchar_t -Fomain.obj main.c
link -out:%PREFIX%\Library\bin\main.exe main.obj
