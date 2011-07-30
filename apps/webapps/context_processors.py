def is_webapps(request):
    return {'WEBAPPS': request.path_info.startswith('/apps/')}
