import os
import mimetypes

from collections import OrderedDict

from django import http, shortcuts
from django.db.transaction import non_atomic_requests
from django.utils.translation import ugettext
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import condition
from django.utils.functional import cached_property
from rest_framework import serializers

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.lib.cache import Message, Token
from olympia.lib.git import AddonGitRepository
from olympia.amo.decorators import json_view
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import HttpResponseSendFile, render, urlparams
from olympia.files.decorators import (
    compare_file_view, etag, file_view, file_view_token, last_modified)
from olympia.files.file_viewer import extract_file
from olympia.files.models import File
from olympia.addons.serializers import VersionSerializer
from olympia.api.fields import ReverseChoiceField

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


class AddonFileBrowseSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    platform = ReverseChoiceField(choices=amo.PLATFORM_CHOICES_API.items())
    status = ReverseChoiceField(choices=amo.STATUS_CHOICES_API.items())
    permissions = serializers.ListField(
        source='webext_permissions_list',
        child=serializers.CharField())
    is_restart_required = serializers.BooleanField()
    # TODO: Do we need the add-on serialized as well?
    version = VersionSerializer()
    validation_url_json = serializers.SerializerMethodField()
    validation_url = serializers.SerializerMethodField()
    has_been_validated = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()
    files = serializers.SerializerMethodField()
    git_hex = serializers.SerializerMethodField()
    git_message = serializers.SerializerMethodField()
    git_author = serializers.SerializerMethodField()

    class Meta:
        model = File
        fields = ('id', 'created', 'hash', 'is_restart_required',
                  'is_webextension', 'is_mozilla_signed_extension',
                  'platform', 'size', 'status', 'url', 'permissions',
                  'automated_signing', 'has_been_validated')

    @cached_property
    def repo(self):
        return AddonGitRepository(self.instance.version.addon)

    @property
    def git_repo(self):
        return self.repo.git_repository

    def _get_commit(self, file_obj):
        """Return the pygit2 repository instance, preselect correct channel."""
        return self.git_repo.revparse_single(file_obj.version.git_hash)

    def get_url(self, obj):
        # File.get_url_path() is a little different, it's already absolute, but
        # needs a src parameter that is appended as a query string.
        return obj.get_url_path(src='')

    def get_validation_url_json(self, obj):
        return reverse('devhub.json_file_validation', args=[
            obj.version.addon.slug, obj.id
        ])

    def get_validation_url(self, obj):
        return reverse('devhub.file_validation', args=[
            obj.version.addon.slug, obj.id
        ])

    def get_files(self, obj):
        commit = self._get_commit(obj)
        result = OrderedDict()

        for wrapper in self.repo.iter_tree(commit.tree):
            entry = wrapper.tree_entry
            path = wrapper.path

            mime, encoding = mimetypes.guess_type(entry.name)

            result[entry.path] = {
                'id': self.file.id,
                'binary': self._is_binary(mime, path),
                'depth': path.count(os.sep),
                'directory': entry.type == 'tree',
                'filename': entry.name,
                # 'sha256': get_sha256(path) if not directory else '',
                'mimetype': mime or 'application/octet-stream',
                'syntax': self.get_syntax(entry.name),
                # 'modified': os.stat(path)[stat.ST_MTIME],
                'short': entry.path,
                # 'size': os.stat(path)[stat.ST_SIZE],
                # 'truncated': self.truncate(filename),
                'version': self.file.version.version,
            }

        return result

    # if viewer.is_extracted():
    #     data.update({'status': True, 'files': viewer.get_files()})
    #     key = viewer.get_default(key)
    #     if key not in data['files']:
    #         raise http.Http404

    #     viewer.select(key)
    #     data['key'] = key
    #     if (not viewer.is_directory() and not viewer.is_binary()):
    #         data['content'] = viewer.read_file()

    # tmpl = 'files/content.html' if type == 'fragment' else 'files/viewer.html'
    # return render(request, tmpl, data)







# class BrowseViewSet(RetrieveModelMixin, GenericViewSet):
#     permission_classes = [AnyOf(
#         AllowReviewer, AllowReviewerUnlisted, AllowAddonAuthor,
#     )]

#     serializer_class = AddonFileBrowseSerializer

#     def get_queryset(self):
#         """Return queryset to be used for the view."""
#         # Special case: admins - and only admins - can see deleted add-ons.
#         # This is handled outside a permission class because that condition
#         # would pollute all other classes otherwise.
#         if (self.request.user.is_authenticated and
#                 acl.action_allowed(self.request,
#                                    amo.permissions.ADDONS_VIEW_DELETED)):
#             return Addon.unfiltered.all()
#         # Permission classes disallow access to non-public/unlisted add-ons
#         # unless logged in as a reviewer/addon owner/admin, so we don't have to
#         # filter the base queryset here.
#         return Addon.objects.all()

#     def get_serializer_class(self):
#         # Override serializer to use serializer_class_with_unlisted_data if
#         # we are allowed to access unlisted data.
#         obj = getattr(self, 'instance')
#         request = self.request
#         if (acl.check_unlisted_addons_reviewer(request) or
#                 (obj and request.user.is_authenticated and
#                  obj.authors.filter(pk=request.user.pk).exists())):
#             return self.serializer_class_with_unlisted_data
#         return self.serializer_class

#     def get_lookup_field(self, identifier):
#         lookup_field = 'pk'
#         if identifier and not identifier.isdigit():
#             # If the identifier contains anything other than a digit, it's
#             # either a slug or a guid. guids need to contain either {} or @,
#             # which are invalid in a slug.
#             if amo.ADDON_GUID_PATTERN.match(identifier):
#                 lookup_field = 'guid'
#             else:
#                 lookup_field = 'slug'
#         return lookup_field

#     def get_object(self):
#         identifier = self.kwargs.get('pk')
#         self.lookup_field = self.get_lookup_field(identifier)
#         self.kwargs[self.lookup_field] = identifier
#         self.instance = super(AddonViewSet, self).get_object()
#         return self.instance

