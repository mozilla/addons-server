from django.conf import settings

from amo.urlresolvers import get_url_prefix, reverse, url_fix


def remora_url(url, lang=None, app=None, prefix=''):
    """
    Builds a remora-style URL, independent from Zamboni's prefixer logic.
    If app and/or lang are None, the current Zamboni values will be used.
    To omit them from the URL, set them to ''.
    """
    prefixer = get_url_prefix()
    if lang is None:
        lang = getattr(prefixer, 'locale', settings.LANGUAGE_CODE)
    if app is None:
        app = getattr(prefixer, 'app', settings.DEFAULT_APP)

    url_parts = [p for p in (prefix.strip('/'), lang, app, url.lstrip('/'))
                 if p]

    return url_fix('/'+'/'.join(url_parts))
