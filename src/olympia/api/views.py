from drf_spectacular.views import SpectacularSwaggerSplitView


def serve_swagger_ui_js(request, version):
    # Add script parameter to ensure we return the swagger UI JS file
    request.GET = request.GET.copy()
    request.GET['script'] = '1'
    return SpectacularSwaggerSplitView.as_view(url_name=f'{version}:schema')(request)
