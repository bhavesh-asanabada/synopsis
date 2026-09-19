"""Shared default filesystem locations, valid for both a source checkout and an installed package."""
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
# A source checkout has app.py next to the synopsis package; an installed package does not.
_RUNNING_FROM_SOURCE = (PROJECT_ROOT / 'app.py').exists()


def default_data_dir():
    if _RUNNING_FROM_SOURCE:
        return PROJECT_ROOT / 'data'
    return Path.home() / '.synopsis' / 'data'


def default_model_cache_dir():
    return default_data_dir() / 'models'
