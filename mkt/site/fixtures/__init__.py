import os

from django.conf import settings
from django.core.management.color import color_style


def fixture(*names):
    files = []
    for name in names:
        filename = os.path.join(settings.ROOT, 'mkt/site/fixtures/data', name)
        if not os.path.splitext(filename)[1]:
            filename += '.json'
        if not os.path.exists(filename):
            print color_style().ERROR('No fixture: %s, skipping.' % filename)
            continue
        files.append(filename)

    return files
