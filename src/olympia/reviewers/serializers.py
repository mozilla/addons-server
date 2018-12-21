import io
import os
import mimetypes
from collections import OrderedDict

import pygit2

from rest_framework import serializers
from rest_framework.exceptions import NotFound

from django.utils.functional import cached_property

from olympia import amo
from olympia.amo.urlresolvers import reverse
from olympia.addons.serializers import VersionSerializer
from olympia.addons.models import AddonReviewerFlags
from olympia.files.utils import get_sha256
from olympia.files.models import File
from olympia.files.file_viewer import denied_extensions, denied_magic_numbers
from olympia.versions.models import Version
from olympia.api.fields import ReverseChoiceField
from olympia.lib.git import AddonGitRepository
from olympia.lib import unicodehelper


class AddonReviewerFlagsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AddonReviewerFlags
        fields = ('auto_approval_disabled', 'needs_admin_code_review',
                  'needs_admin_content_review', 'needs_admin_theme_review',
                  'pending_info_request')


class SimplifiedVersionSerializer(VersionSerializer):
    """Doesn't contain duplicate `files` information."""

    class Meta:
        model = Version
        fields = ('id', 'channel', 'compatibility', 'edit_url',
                  'is_strict_compatibility_enabled', 'license',
                  'release_notes', 'reviewed', 'url', 'version')


class AddonFileBrowseSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    platform = ReverseChoiceField(choices=amo.PLATFORM_CHOICES_API.items())
    status = ReverseChoiceField(choices=amo.STATUS_CHOICES_API.items())
    permissions = serializers.ListField(
        source='webext_permissions_list',
        child=serializers.CharField())
    is_restart_required = serializers.BooleanField()
    version = SimplifiedVersionSerializer()
    validation_url_json = serializers.SerializerMethodField()
    validation_url = serializers.SerializerMethodField()
    has_been_validated = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()
    files = serializers.SerializerMethodField()

    class Meta:
        model = File
        fields = ('id', 'created', 'hash', 'is_restart_required',
                  'is_webextension', 'is_mozilla_signed_extension',
                  'platform', 'size', 'status', 'download_url', 'permissions',
                  'automated_signing', 'has_been_validated',
                  'validation_url_json', 'validation_url',
                  'content', 'version', 'files')

    @cached_property
    def repo(self):
        return AddonGitRepository(self.instance.version.addon)

    @property
    def git_repo(self):
        return self.repo.git_repository

    def _get_commit(self, file_obj):
        """Return the pygit2 repository instance, preselect correct channel."""
        try:
            return self.git_repo.revparse_single(file_obj.version.git_hash)
        except pygit2.InvalidSpecError:
            raise NotFound(
                'Couldn\'t find the requested version in git-repository')

    def get_download_url(self, obj):
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

    def get_has_been_validated(self, obj):
        return obj.has_been_validated

    def _is_binary(self, filepath, mimetype, blob):
        """
        Using filepath, mimetype and in-memory buffer to determine if a file
        can be shown in HTML or not.
        """
        # Re-use the denied data from amo-validator to spot binaries.
        ext = os.path.splitext(filepath)[1][1:]
        if ext in denied_extensions:
            return True

        bytes = tuple(map(ord, memoryview(blob)[:4]))

        if any(bytes[:len(x)] == x for x in denied_magic_numbers):
            return True

        if mimetype:
            major, minor = mimetype.split('/')
            if major == 'image':
                return 'image'  # Mark that the file is binary, but an image.

        return False

    def get_files(self, obj):
        commit = self._get_commit(obj)
        result = OrderedDict()

        for entry_wrapper in self.repo.iter_tree(commit.tree):
            entry = entry_wrapper.tree_entry
            path = entry_wrapper.path
            blob = entry_wrapper.blob

            is_directory = entry.type == 'tree'
            mime, encoding = mimetypes.guess_type(entry.name)
            is_binary = (
                self._is_binary(path, mime, blob)
                if not is_directory else False)
            sha_hash = (
                get_sha256(io.BytesIO(memoryview(blob)))
                if not is_directory else '')

            result[path] = {
                'id': obj.id,
                'binary': is_binary,
                'depth': path.count(os.sep),
                'directory': is_directory,
                'filename': entry.name,
                'sha256': sha_hash,
                'mimetype': mime or 'application/octet-stream',
                'path': path,
                'size': blob.size if blob is not None else None,
                'version': obj.version.version,
                'modified': commit.commit_time,
            }

        return result

    def get_selected_file(self, files=None):
        requested_file = self.context.get('file', None)

        if requested_file is None:
            if files is None:
                files = self.get_files(self.instance)
            for manifest in ('install.rdf', 'manifest.json', 'package.json'):
                if manifest in files:
                    requested_file = manifest

        return requested_file

    def get_content(self, obj):
        commit = self._get_commit(obj)
        blob_or_tree = commit.tree[self.get_selected_file()]

        if blob_or_tree.type == 'blob':
            # TODO: Test if this is actually needed, historically it was
            # because files inside a zip could have any encoding but I'm not
            # sure if git unifies this to some degree (cgrebs)
            return unicodehelper.decode(
                self.git_repo[blob_or_tree.oid].read_raw())
