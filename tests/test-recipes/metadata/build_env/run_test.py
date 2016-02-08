import os

def main():
    undef_var1 = os.environ.get("UNDEF_VAR1")
    undef_var2 = os.environ.get("UNDEF_VAR2")

    assert undef_var1 is None
    assert undef_var2 == "UNDEFINED"

if __name__ == '__main__':
    main()
