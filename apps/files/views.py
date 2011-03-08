import hashlib

from django import http
from django.utils.http import http_date
from django.views.decorators.cache import never_cache

import jingo

from access import acl
from amo.decorators import json_view
from amo.urlresolvers import reverse
from files.decorators import file_view, compare_file_view
from files.tasks import extract_file


def setup_viewer(request, file_obj):
    data = {'file': file_obj,
            'version': file_obj.version,
            'addon': file_obj.version.addon,
            'status': False,
            'selected': {}}

    if acl.action_allowed(request, 'Editors', '%'):
        data['file_url'] = reverse('editors.review', args=[data['version'].pk])
    else:
        data['file_url'] = reverse('addons.detail', args=[data['addon'].pk])
    return data


@never_cache
@json_view
@file_view
def files_poll(request, viewer):
    return {'status': viewer.is_extracted}


@file_view
def files_list(request, viewer, key='install.rdf'):
    data = setup_viewer(request, viewer.file)
    data['viewer'] = viewer
    data['poll_url'] = reverse('files.poll', args=[viewer.file.id])

    if viewer.is_extracted:
        files = viewer.get_files()
        data.update({'status': True, 'files': files})
        if key:
            if key not in files:
                raise http.Http404

            selected = data['selected'] = files.get(key)
            if (not selected['directory'] and
                not selected['binary']):
                    data['content'], data['msg'] = viewer.read_file(selected)

    else:
        extract_file.delay(viewer)

    response = jingo.render(request, 'files/viewer.html', data)
    response['ETag'] = '"%s"' % hashlib.md5(response.content).hexdigest()
    response['Last-Modified'] = http_date(data['selected']['modified'] if
                                          data['selected'] else None)
    return response


@never_cache
@compare_file_view
@json_view
def files_compare_poll(request, diff):
    return {'status': diff.is_extracted}


@compare_file_view
def files_compare(request, diff, key=None):
    data = setup_viewer(request, diff.file_one.file)
    data['diff'] = diff
    data['poll_url'] = reverse('files.compare.poll',
                               args=[diff.file_one.file.id,
                                     diff.file_two.file.id])

    if diff.is_extracted:
        files = diff.primary_files()
        data.update({'status': True, 'files': files})

        if key:
            if key not in files:
                raise http.Http404

            diff.select(key)
            data['selected'] = diff.one
            if not diff.is_diffable():
                data['msg'] = diff.status

            elif not diff.is_binary():
                data['text_one'], omsg = diff.file_one.read_file(diff.one)
                data['text_two'], tmsg = diff.file_two.read_file(diff.two)
                data['msg'] = omsg or tmsg

    else:
        extract_file.delay(diff)

    response = jingo.render(request, 'files/viewer.html', data)
    response['ETag'] = '"%s"' % hashlib.md5(response.content).hexdigest()
    response['Last-Modified'] = http_date(data['selected']['modified'] if
                                          data['selected'] else None)
    return response
