import re

from django.conf import settings


def is_webapps(request):
    if isinstance(request.path_info, basestring):
        is_match = re.match('/(developers/)?apps/', request.path_info)
    else:
        is_match = False
    return {'WEBAPPS': is_match or settings.APP_PREVIEW}
