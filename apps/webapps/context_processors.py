import re

def is_webapps(request):
    is_match = re.match('/(developers/)?apps/', request.path_info)
    return {'WEBAPPS': is_match}
