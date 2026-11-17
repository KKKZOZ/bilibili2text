"""Access the PNG cache index; object expiry is managed by storage lifecycle."""

from b2t.png_cache import PngCache
from backend.settings import get_app_config


def get_png_cache():
    return PngCache(get_app_config().download.db_dir)
