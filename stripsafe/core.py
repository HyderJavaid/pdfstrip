"""File-level entry point: pick a handler by extension and write a cleaned copy."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .images import IMAGE_EXTENSIONS, process_image
from .pdf import PDF_EXTENSIONS, process_pdf
from .presets import Preset

SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | IMAGE_EXTENSIONS
OUTPUT_SUFFIX = "_clean"


@dataclass
class Result:
    source: Path
    output: Optional[Path]
    original_size: int
    new_size: int
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def saved_percent(self) -> float:
        if not self.original_size:
            return 0.0
        return 100.0 * (self.original_size - self.new_size) / self.original_size


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def output_path_for(source: Path, output_dir: Optional[Path] = None) -> Path:
    """``name_clean.ext`` next to the source (or in output_dir), never clobbering anything."""
    folder = output_dir or source.parent
    candidate = folder / f"{source.stem}{OUTPUT_SUFFIX}{source.suffix}"
    n = 2
    while candidate.exists() or candidate.resolve() == source.resolve():
        candidate = folder / f"{source.stem}{OUTPUT_SUFFIX}_{n}{source.suffix}"
        n += 1
    return candidate


def clean_bytes(data: bytes, ext: str, preset: Preset) -> bytes:
    ext = ext.lower()
    if ext in PDF_EXTENSIONS:
        return process_pdf(data, preset)
    return process_image(data, ext, preset)


def process_file(source, preset: Preset, output_dir=None) -> Result:
    source = Path(source)
    output_dir = Path(output_dir) if output_dir else None
    try:
        data = source.read_bytes()
    except OSError as exc:
        return Result(source, None, 0, 0, f"Could not read file: {exc}")
    if not is_supported(source):
        return Result(source, None, len(data), 0, f"Unsupported file type: {source.suffix or '(none)'}")
    try:
        cleaned = clean_bytes(data, source.suffix, preset)
    except Exception as exc:  # report per-file, keep the batch going
        return Result(source, None, len(data), 0, str(exc) or exc.__class__.__name__)
    target = output_path_for(source, output_dir)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "xb") as fh:  # "x" refuses to overwrite an existing file
            fh.write(cleaned)
    except OSError as exc:
        return Result(source, None, len(data), 0, f"Could not write output: {exc}")
    return Result(source, target, len(data), len(cleaned))


def expand_paths(paths):
    """Turn a mix of files and folders into the supported files they contain."""
    found = []
    for p in map(Path, paths):
        if p.is_dir():
            found.extend(sorted(f for f in p.rglob("*") if f.is_file() and is_supported(f)
                                and not f.stem.endswith(OUTPUT_SUFFIX)))
        else:
            found.append(p)
    return found


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"
