from app.core.settings import ensure_directories as _ensure_directories
from app.core.settings import get_settings


_SETTINGS = get_settings()

BASE_DIR = _SETTINGS.base_dir
DATA_DIR = _SETTINGS.data_dir
DB_PATH = _SETTINGS.db_path
MEDIA_ROOT = _SETTINGS.media_root
REGISTER_IMAGE_DIR = _SETTINGS.register_image_dir
CHECKIN_IMAGE_DIR = _SETTINGS.checkin_image_dir


def ensure_directories() -> None:
    _ensure_directories(_SETTINGS)
