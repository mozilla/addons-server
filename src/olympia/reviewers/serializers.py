import io
import os
import mimetypes
from collections import OrderedDict
from datetime import datetime

import pygit2

from rest_framework import serializers
from rest_framework.exceptions import NotFound

from django.utils.functional import cached_property
from django.utils.encoding import force_text
from django.utils.timezone import FixedOffset

from olympia.amo.urlresolvers import reverse
from olympia.addons.serializers import (
    VersionSerializer, FileSerializer, SimpleAddonSerializer)
from olympia.addons.models import AddonReviewerFlags
from olympia.files.utils import get_sha256
from olympia.files.models import File
from olympia.files.file_viewer import denied_extensions, denied_magic_numbers
from olympia.versions.models import Version
from olympia.lib.git import AddonGitRepository
from olympia.lib import unicodehelper
from olympia.lib.cache import cache_get_or_set


class AddonReviewerFlagsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AddonReviewerFlags
        fields = ('auto_approval_disabled', 'needs_admin_code_review',
                  'needs_admin_content_review', 'needs_admin_theme_review',
                  'pending_info_request')


class FileEntriesSerializer(FileSerializer):
    content = serializers.SerializerMethodField()
    entries = serializers.SerializerMethodField()
    selected_file = serializers.SerializerMethodField()

    class Meta:
        fields = FileSerializer.Meta.fields + (
            'content', 'entries', 'selected_file'
        )
        model = File

    @cached_property
    def repo(self):
        return AddonGitRepository(self.get_instance().version.addon)

    @property
    def git_repo(self):
        return self.repo.git_repository

    def get_instance(self):
        """Fetch the correct instance either from this serializer or
        it's parent"""
        if self.parent is not None:
            return self.parent.instance.current_file
        return self.instance

    def _get_commit(self, file_obj):
        """Return the pygit2 repository instance, preselect correct channel."""
        try:
            return self.git_repo.revparse_single(file_obj.version.git_hash)
        except pygit2.InvalidSpecError:
            raise NotFound(
                'Couldn\'t find the requested version in git-repository')

    def get_entries(self, obj):
        # Given that this is a very expensive operation we have a two-fold
        # cache, one that is stored on this instance for very-fast retrieval
        # to support other method calls on this serializer
        # and another that uses memcached for regular caching
        if hasattr(self, '_entries'):
            return self._entries

        commit = self._get_commit(obj)
        result = OrderedDict()

        def _fetch_entries():
            tree = self.repo.get_root_tree(commit)
            for entry_wrapper in self.repo.iter_tree(tree):
                entry = entry_wrapper.tree_entry
                path = force_text(entry_wrapper.path)
                blob = entry_wrapper.blob

                is_directory = entry.type == 'tree'
                mime, encoding = mimetypes.guess_type(entry.name)
                is_binary = (
                    self.is_binary(path, mime, blob)
                    if not is_directory else False)
                sha_hash = (
                    get_sha256(io.BytesIO(memoryview(blob)))
                    if not is_directory else '')

                commit_tzinfo = FixedOffset(commit.commit_time_offset)
                commit_time = datetime.fromtimestamp(
                    float(commit.commit_time),
                    commit_tzinfo)

                result[path] = {
                    'binary': is_binary,
                    'depth': path.count(os.sep),
                    'directory': is_directory,
                    'filename': force_text(entry.name),
                    'sha256': sha_hash,
                    'mimetype': mime or 'application/octet-stream',
                    'path': path,
                    'size': blob.size if blob is not None else None,
                    'modified': commit_time,
                }
            return result

        self._entries = cache_get_or_set(
            'reviewers:fileentriesserializer:entries:{}'.format(commit.hex),
            _fetch_entries,
            # Store information about this commit for 24h which should be
            # enough to cover regular review-times but not overflow our
            # cache
            60 * 60 * 24)

        return self._entries

    def is_binary(self, filepath, mimetype, blob):
        """
        Using filepath, mimetype and in-memory buffer to determine if a file
        can be shown in HTML or not.
        """
        # Re-use the denied data from amo-validator to spot binaries.
        ext = os.path.splitext(filepath)[1][1:]
        if ext in denied_extensions:
            return True

        bytes_ = tuple(bytearray(memoryview(blob)[:4]))

        if any(bytes_[:len(x)] == x for x in denied_magic_numbers):
            return True

        if mimetype:
            major, minor = mimetype.split('/')
            if major == 'image':
                return 'image'  # Mark that the file is binary, but an image.

        return False

    def get_selected_file(self, obj):
        requested_file = self.context.get('file', None)

        if requested_file is None:
            files = self.get_entries(obj)

            for manifest in ('manifest.json', 'install.rdf', 'package.json'):
                if manifest in files:
                    requested_file = manifest
                    break
            else:
                # This could be a search engine
                requested_file = files.keys()[0]

        return requested_file

    def get_content(self, obj):
        commit = self._get_commit(obj)
        tree = self.repo.get_root_tree(commit)
        blob_or_tree = tree[self.get_selected_file(obj)]

        if blob_or_tree.type == 'blob':
            # TODO: Test if this is actually needed, historically it was
            # because files inside a zip could have any encoding but I'm not
            # sure if git unifies this to some degree (cgrebs)
            return unicodehelper.decode(
                self.git_repo[blob_or_tree.oid].read_raw())


class AddonBrowseVersionSerializer(VersionSerializer):
    validation_url_json = serializers.SerializerMethodField()
    validation_url = serializers.SerializerMethodField()
    has_been_validated = serializers.SerializerMethodField()
    file = FileEntriesSerializer(source='current_file')
    addon = SimpleAddonSerializer()

    class Meta:
        model = Version
        # Doesn't contain `files` from VersionSerializer
        fields = ('id', 'channel', 'compatibility', 'edit_url',
                  'is_strict_compatibility_enabled', 'license',
                  'release_notes', 'reviewed', 'version',
                  # Our custom fields
                  'file', 'validation_url', 'validation_url_json',
                  'has_been_validated', 'addon')

    def get_validation_url_json(self, obj):
        return reverse('devhub.json_file_validation', args=[
            obj.addon.slug, obj.current_file.id
        ])

    def get_validation_url(self, obj):
        return reverse('devhub.file_validation', args=[
            obj.addon.slug, obj.current_file.id
        ])

    def get_has_been_validated(self, obj):
        return obj.current_file.has_been_validated


class DiffableVersionSerializer(VersionSerializer):
    should_show_channel = serializers.SerializerMethodField()

    class Meta:
        model = Version
        fields = ('id', 'channel', 'url', 'version', 'should_show_channel')

    def get_should_show_channel(self, obj):
        return self.context.get('should_show_channel', False)
