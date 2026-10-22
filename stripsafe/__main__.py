import sys


def main() -> int:
    from .gui import main as gui_main
    return gui_main(sys.argv[1:])  # files given on the command line are queued in the window


if __name__ == "__main__":
    sys.exit(main())
