import hashlib
import json

from django import http
from django.conf import settings
from django.utils.http import http_date
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

import commonware.log
import jingo
import waffle

from access import acl
from amo.decorators import json_view, post_required
from amo.urlresolvers import reverse
from amo.utils import HttpResponseSendFile, Message, Token
from files.decorators import file_view, compare_file_view, file_view_token
from files.tasks import extract_file, repackage_jetpack

from tower import ugettext as _


log = commonware.log.getLogger('z.addons')


def setup_viewer(request, file_obj):
    data = {'file': file_obj,
            'version': file_obj.version,
            'addon': file_obj.version.addon,
            'status': False,
            'selected': {}}

    if acl.action_allowed(request, 'Editors', '%'):
        data['file_link'] = {'text': _('Back to review'),
                             'url': reverse('editors.review',
                                            args=[data['version'].pk])}
    else:
        data['file_link'] = {'text': _('Back to addon'),
                             'url': reverse('addons.detail',
                                            args=[data['addon'].pk])}
    return data


@never_cache
@json_view
@file_view
def poll(request, viewer):
    return {'status': viewer.is_extracted(),
            'msg': [Message('file-viewer:%s' % viewer).get(delete=True)]}


@file_view
def browse(request, viewer, key=None):
    data = setup_viewer(request, viewer.file)
    data['viewer'] = viewer
    data['poll_url'] = reverse('files.poll', args=[viewer.file.id])

    if (not waffle.switch_is_active('delay-file-viewer') and
        not viewer.is_extracted):
        extract_file(viewer)

    if viewer.is_extracted():
        data.update({'status': True, 'files': viewer.get_files()})
        key = viewer.get_default(key)
        if key not in data['files']:
            raise http.Http404

        viewer.select(key)
        data['selected'] = viewer.selected
        if (not viewer.is_directory() and not viewer.is_binary()):
            data['content'] = viewer.read_file()

    else:
        extract_file.delay(viewer)

    tmpl = 'files/content.html' if request.is_ajax() else 'files/viewer.html'
    response = jingo.render(request, tmpl, data)
    if not settings.DEBUG:
        response['ETag'] = '"%s"' % hashlib.md5(response.content).hexdigest()
        response['Last-Modified'] = http_date(data['selected']['modified'] if
                                              data['selected'] else None)
    return response


@never_cache
@compare_file_view
@json_view
def compare_poll(request, diff):
    msgs = []
    for f in (diff.left, diff.right):
        m = Message('file-viewer:%s' % f).get(delete=True)
        if m:
            msgs.append(m)
    return {'status': diff.is_extracted(), 'msg': msgs}


@compare_file_view
def compare(request, diff, key=None):
    data = setup_viewer(request, diff.left.file)
    data['diff'] = diff
    data['poll_url'] = reverse('files.compare.poll',
                               args=[diff.left.file.id,
                                     diff.right.file.id])

    if (not waffle.switch_is_active('delay-file-viewer')
        and not diff.is_extracted):
        extract_file(diff.left)
        extract_file(diff.right)

    if diff.is_extracted():
        data.update({'status': True, 'files': diff.get_files()})
        key = diff.left.get_default(key)
        if key not in data['files']:
            raise http.Http404

        diff.select(key)
        data['selected'] = diff.left.selected
        if not diff.is_diffable():
            data['msgs'] = [diff.status]

        elif not diff.is_binary():
            data['left'], data['right'] = diff.read_file()

    else:
        extract_file.delay(diff.left)
        extract_file.delay(diff.right)

    tmpl = 'files/content.html' if request.is_ajax() else 'files/viewer.html'
    response = jingo.render(request, tmpl, data)
    if not settings.DEBUG:
        response['ETag'] = '"%s"' % hashlib.md5(response.content).hexdigest()
        response['Last-Modified'] = http_date(data['selected']['modified'] if
                                              data['selected'] else None)
    return response


@file_view
def redirect(request, viewer, key):
    new = Token(data=[request.META.get('REMOTE_ADDR'), viewer.file.id, key])
    new.save()
    url = '%s%s?token=%s' % (settings.STATIC_URL,
                             reverse('files.serve', args=[viewer, key]),
                             new.token)
    return http.HttpResponseRedirect(url)


@file_view_token
def serve(request, viewer, key):
    """
    This is to serve files off of st.a.m.o, not standard a.m.o. For this we
    use token based authentication.
    """
    files = viewer.get_files()
    obj = files.get(key)
    if not obj:
        log.error(u'Couldn\'t find %s in %s (%d entries) for file %s' %
                  (key, files.keys()[:10], len(files.keys()), viewer.file.id))
        raise http.Http404()
    return HttpResponseSendFile(request, obj['full'],
                                content_type=obj['mimetype'])


@csrf_exempt
@post_required
def builder_pingback(request):
    try:
        data = json.loads(request.raw_post_data)
        data['id']  # Ensure id is available.
        assert data.get('secret') == settings.BUILDER_SECRET_KEY
    except Exception:
        return http.HttpResponseBadRequest()
    repackage_jetpack(data)
    return http.HttpResponse()
