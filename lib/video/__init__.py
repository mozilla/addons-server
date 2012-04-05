from django.conf import settings
from django.utils.importlib import import_module

_library = None


def get_library():
    """Find a suitable lib."""
    for lib in settings.VIDEO_LIBRARIES:
        mod = import_module(lib)
        if mod.Video.library_available():
            return mod.Video


if _library is None:
    _library = get_library()

library = _library
