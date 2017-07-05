#include <libgreeting.h>
#include <stdio.h>

#define STRINGIZE2(_x) #_x
#define STRINGIZE(_x) STRINGIZE2(_x)

int main(int argc, char * argv[])
{
    char * say_it = greeting(STRINGIZE(GREETING_SUFFIX));
    if (say_it != NULL)
    {
        puts(say_it);
        puts("\n");
        return 0;
    }
    return 1;
}
