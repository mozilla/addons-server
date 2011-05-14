import hashlib

from django import http
from django.conf import settings
from django.utils.http import http_date
from django.views.decorators.cache import never_cache

import commonware.log
import jingo
import waffle

from access import acl
from amo.decorators import json_view
from amo.urlresolvers import reverse
from amo.utils import HttpResponseSendFile, Message, Token
from files.decorators import file_view, compare_file_view, file_view_token
from files.tasks import extract_file

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
                                            args=[file_obj.version.pk])}
    else:
        data['file_link'] = {'text': _('Back to addon'),
                             'url': reverse('addons.detail',
                                            args=[file_obj.version.addon.pk])}
    return data


@never_cache
@json_view
@file_view
def poll(request, viewer):
    return {'status': viewer.is_extracted,
            'msg': [Message('file-viewer:%s' % viewer).get(delete=True)]}


@file_view
def browse(request, viewer, key=None):
    data = setup_viewer(request, viewer.file)
    data['viewer'] = viewer
    data['poll_url'] = reverse('files.poll', args=[viewer.file.id])

    if (not waffle.switch_is_active('delay-file-viewer')
        and not viewer.is_extracted):
        extract_file(viewer)

    if viewer.is_extracted:
        files = viewer.get_files()
        data.update({'status': True, 'files': files})
        key = viewer.get_default(key)
        if key not in files:
            raise http.Http404

        selected = data['selected'] = files.get(key)
        if (not selected['directory'] and not selected['binary']):
            data['content'], data['msg'] = viewer.read_file(selected)

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
    for f in (diff.file_one, diff.file_two):
        m = Message('file-viewer:%s' % f).get(delete=True)
        if m:
            msgs.append(m)
    return {'status': diff.is_extracted, 'msg': msgs}


@compare_file_view
def compare(request, diff, key=None):
    data = setup_viewer(request, diff.file_one.file)
    data['diff'] = diff
    data['poll_url'] = reverse('files.compare.poll',
                               args=[diff.file_one.file.id,
                                     diff.file_two.file.id])

    if (not waffle.switch_is_active('delay-file-viewer')
        and not diff.is_extracted):
        extract_file(diff.file_one)
        extract_file(diff.file_two)

    if diff.is_extracted:
        files = diff.get_files()
        data.update({'status': True, 'files': files})
        key = diff.file_one.get_default(key)
        if key not in files:
            raise http.Http404

        diff.select(key)
        data['selected'] = diff.one
        if not diff.is_diffable():
            data['msg'] = diff.status

        elif not diff.is_binary():
            data['one'], omsg = diff.file_one.read_file(diff.one)
            data['two'], tmsg = diff.file_two.read_file(diff.two)
            data['msg'] = omsg or tmsg

    else:
        extract_file.delay(diff.file_one)
        extract_file.delay(diff.file_two)

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
