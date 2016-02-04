from .utils import VideoBase


class Video(VideoBase):
    """Used for testing."""

    @classmethod
    def library_available(cls):
        return True
