from django.conf import settings
from django.contrib.staticfiles.storage import (
    ManifestStaticFilesStorage,
    StaticFilesStorage,
)


class ManifestStaticFilesStorageNotMaps(ManifestStaticFilesStorage):
    patterns = (
        (
            '*.css',
            (
                # These regexs are copied from HashedFilesMixin in django4.1+
                r"""(?P<matched>url\(['"]{0,1}\s*(?P<url>.*?)["']{0,1}\))""",
                (
                    r"""(?P<matched>@import\s*["']\s*(?P<url>.*?)["'])""",
                    """@import url("%(url)s")""",
                ),
                # We are ommiting the sourceMappingURL regexs for .css and .js as they
                # don't work how we copy over the souces in Makefile-docker.copy_node_js
            ),
        ),
    )


OlympiaStaticFilesStorage = (
    StaticFilesStorage if settings.DEV_MODE else ManifestStaticFilesStorageNotMaps
)
