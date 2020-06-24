#include <stdio.h>

#if !defined(SUFFIX)
#define SUFFIX_STR "A test string"
#else
#define STRINGIZE2(_x) #_x
#define STRINGIZE(_x) STRINGIZE2(_x)
#define SUFFIX_STR STRINGIZE(SUFFIX)
#endif

int main(int argc, char * argv[])
{
    printf("Hello World!\n" SUFFIX_STR "\n");
    return 0;
}
