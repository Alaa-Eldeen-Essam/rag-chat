from __future__ import annotations

from typing import Optional

try:
    from models.db_schemes import Asset
except ImportError:  # pragma: no cover - type hints only
    Asset = None  # type: ignore


def get_asset_display_name(asset: Asset) -> Optional[str]:
    """
    Returns a human-friendly name for the given asset, preferring the original
    filename stored in asset_config. Falls back to the stored asset name.
    """
    if asset is None:
        return None

    original_name = None
    asset_config = getattr(asset, "asset_config", None)

    if isinstance(asset_config, dict):
        raw_name = asset_config.get("original_filename")
        if isinstance(raw_name, str):
            stripped = raw_name.strip()
            if stripped:
                original_name = stripped

    if original_name:
        return original_name

    fallback_name = getattr(asset, "asset_name", None)
    if isinstance(fallback_name, str):
        return fallback_name

    return None
