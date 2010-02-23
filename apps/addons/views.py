from django import http


# pylint: disable-msg: W0613
def addon_detail(request, addon_id):
    return http.HttpResponse('this is addon %s' % addon_id)
