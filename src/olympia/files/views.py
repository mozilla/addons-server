from django import http, shortcuts
from django.db.transaction import non_atomic_requests
from django.utils.translation import ugettext
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import condition

import olympia.core.logger

from olympia.access import acl
from olympia.amo.cache_nuggets import Message, Token
from olympia.amo.decorators import json_view
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import HttpResponseSendFile, render, urlparams
from olympia.files.decorators import (
    compare_file_view, etag, file_view, file_view_token, last_modified)
from olympia.files.templatetags.jinja_helpers import extract_file

from . import forms


log = olympia.core.logger.getLogger('z.addons')


def setup_viewer(request, file_obj):
    addon = file_obj.version.addon
    data = {
        'file': file_obj,
        'version': file_obj.version,
        'addon': addon,
        'status': False,
        'selected': {},
        'validate_url': ''
    }
    is_user_a_reviewer = acl.is_reviewer(request, addon)

    if (is_user_a_reviewer or acl.check_addon_ownership(
            request, addon, dev=True, ignore_disabled=True)):

        data['validate_url'] = reverse('devhub.json_file_validation',
                                       args=[addon.slug, file_obj.id])
        data['automated_signing'] = file_obj.automated_signing

        if file_obj.has_been_validated:
            data['validation_data'] = file_obj.validation.processed_validation

    if is_user_a_reviewer:
        data['file_link'] = {
            'text': ugettext('Back to review'),
            'url': reverse('reviewers.review', args=[addon.slug])
        }
    else:
        data['file_link'] = {
            'text': ugettext('Back to add-on'),
            'url': reverse('addons.detail', args=[addon.pk])
        }
    return data


@never_cache
@json_view
@file_view
@non_atomic_requests
def poll(request, viewer):
    return {'status': viewer.is_extracted(),
            'msg': [Message('file-viewer:%s' % viewer).get(delete=True)]}


def check_compare_form(request, form):
    if request.method == 'POST':
        if form.is_valid():
            left = form.cleaned_data['left']
            right = form.cleaned_data.get('right')
            if right:
                url = reverse('files.compare', args=[left, right])
            else:
                url = reverse('files.list', args=[left])
        else:
            url = request.path
        return shortcuts.redirect(url)


@csrf_exempt
@file_view
@non_atomic_requests
@condition(etag_func=etag, last_modified_func=last_modified)
def browse(request, viewer, key=None, type='file'):
    form = forms.FileCompareForm(request.POST or None, addon=viewer.addon,
                                 initial={'left': viewer.file},
                                 request=request)
    response = check_compare_form(request, form)
    if response:
        return response

    data = setup_viewer(request, viewer.file)
    data['viewer'] = viewer
    data['poll_url'] = reverse('files.poll', args=[viewer.file.id])
    data['form'] = form

    if not viewer.is_extracted():
        extract_file(viewer)

    if viewer.is_extracted():
        data.update({'status': True, 'files': viewer.get_files()})
        key = viewer.get_default(key)
        if key not in data['files']:
            raise http.Http404

        viewer.select(key)
        data['key'] = key
        if (not viewer.is_directory() and not viewer.is_binary()):
            data['content'] = viewer.read_file()

    tmpl = 'files/content.html' if type == 'fragment' else 'files/viewer.html'
    return render(request, tmpl, data)


@never_cache
@compare_file_view
@json_view
@non_atomic_requests
def compare_poll(request, diff):
    msgs = []
    for f in (diff.left, diff.right):
        m = Message('file-viewer:%s' % f).get(delete=True)
        if m:
            msgs.append(m)
    return {'status': diff.is_extracted(), 'msg': msgs}


@csrf_exempt
@compare_file_view
@condition(etag_func=etag, last_modified_func=last_modified)
@non_atomic_requests
def compare(request, diff, key=None, type='file'):
    form = forms.FileCompareForm(request.POST or None, addon=diff.addon,
                                 initial={'left': diff.left.file,
                                          'right': diff.right.file},
                                 request=request)
    response = check_compare_form(request, form)
    if response:
        return response

    data = setup_viewer(request, diff.left.file)
    data['diff'] = diff
    data['poll_url'] = reverse('files.compare.poll',
                               args=[diff.left.file.id,
                                     diff.right.file.id])
    data['form'] = form

    if not diff.is_extracted():
        extract_file(diff.left)
        extract_file(diff.right)

    if diff.is_extracted():
        data.update({'status': True,
                     'files': diff.get_files(),
                     'files_deleted': diff.get_deleted_files()})
        key = diff.left.get_default(key)
        if key not in data['files'] and key not in data['files_deleted']:
            raise http.Http404

        diff.select(key)
        data['key'] = key
        if diff.is_diffable():
            data['left'], data['right'] = diff.read_file()

    tmpl = 'files/content.html' if type == 'fragment' else 'files/viewer.html'
    return render(request, tmpl, data)


@file_view
@non_atomic_requests
def redirect(request, viewer, key):
    new = Token(data=[viewer.file.id, key])
    new.save()
    url = reverse('files.serve', args=[viewer, key])
    url = urlparams(url, token=new.token)
    return http.HttpResponseRedirect(url)


@file_view_token
@non_atomic_requests
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
        raise http.Http404
    return HttpResponseSendFile(request, obj['full'],
                                content_type=obj['mimetype'])
