"""Compression presets shared by the PDF and image pipelines."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Preset:
    name: str
    label: str
    # JPEG quality for re-encoded images; None means never re-encode (lossless only).
    jpeg_quality: Optional[int]
    # Longest image side in pixels after downscaling; None means keep full resolution.
    max_dimension: Optional[int]


PRESETS = {
    "lossless": Preset("lossless", "Strip only (lossless)", None, None),
    "light": Preset("light", "Light compression", 85, 3000),
    "balanced": Preset("balanced", "Balanced (recommended)", 75, 2000),
    "strong": Preset("strong", "Strong (smallest files)", 60, 1400),
}

DEFAULT_PRESET = "balanced"


def get_preset(name: str) -> Preset:
    try:
        return PRESETS[name]
    except KeyError:
        raise ValueError(f"Unknown preset {name!r}; choose from {', '.join(PRESETS)}") from None
