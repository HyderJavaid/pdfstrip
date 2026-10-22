"""Command-line interface, handy for scripting and for machines without a display."""

import argparse
import sys

from .core import expand_paths, human_size, process_file
from .presets import DEFAULT_PRESET, PRESETS, get_preset


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="stripsafe",
        description="Strip private metadata from PDFs and images and shrink them. Runs fully offline.",
    )
    parser.add_argument("files", nargs="+", help="PDF/JPEG/PNG/WebP files or folders")
    parser.add_argument("-p", "--preset", choices=list(PRESETS), default=DEFAULT_PRESET,
                        help=f"compression level (default: {DEFAULT_PRESET})")
    parser.add_argument("-o", "--output-dir", help="write cleaned files here instead of next to the originals")
    args = parser.parse_args(argv)

    preset = get_preset(args.preset)
    failures = 0
    for path in expand_paths(args.files):
        r = process_file(path, preset, args.output_dir)
        if r.ok:
            print(f"OK   {r.source} -> {r.output}  "
                  f"{human_size(r.original_size)} -> {human_size(r.new_size)} ({r.saved_percent:+.0f}% saved)")
        else:
            failures += 1
            print(f"FAIL {r.source}: {r.error}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
