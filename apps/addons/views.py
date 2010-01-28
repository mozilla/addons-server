from django import http


def addon_detail(request, addon_id):
    return http.HttpResponse('this is addon %s' % addon_id)
