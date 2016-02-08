import os

def main():
    undef_var = os.environ.get("UNDEF_VAR")

    assert undef_var is None

if __name__ == '__main__':
    main()
