import os

from django.conf import settings


def fixture(*names):
    return [os.path.join(settings.ROOT, 'mkt/site/fixtures/data', n)
            for n in names]
