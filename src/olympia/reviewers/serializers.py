import io
import os
import mimetypes
import pathlib
import json
from collections import OrderedDict
from datetime import datetime, timezone, timedelta

import pygit2

from rest_framework import serializers
from rest_framework.exceptions import NotFound

from django.core.cache import cache
from django.utils.functional import cached_property
from django.utils.encoding import force_text
from django.utils.translation import ugettext

from olympia import amo
from olympia.activity.models import DraftComment
from olympia.accounts.serializers import BaseUserSerializer
from olympia.amo.urlresolvers import reverse
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.addons.serializers import (
    FileSerializer, MinimalVersionSerializer, SimpleAddonSerializer)
from olympia.addons.models import AddonReviewerFlags
from olympia.api.fields import ReverseChoiceField, SplitField
from olympia.users.models import UserProfile
from olympia.files.utils import get_sha256
from olympia.files.models import File, FileValidation
from olympia.reviewers.models import CannedResponse
from olympia.versions.models import Version
from olympia.lib.git import AddonGitRepository, get_mime_type_for_blob
from olympia.lib.cache import make_key
from olympia.lib import unicodehelper


class AddonReviewerFlagsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AddonReviewerFlags
        fields = (
            'auto_approval_disabled',
            'auto_approval_delayed_until',
            'needs_admin_code_review',
            'needs_admin_content_review',
            'needs_admin_theme_review',
            'pending_info_request'
        )


class FileEntriesSerializer(FileSerializer):
    content = serializers.SerializerMethodField()
    uses_unknown_minified_code = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    entries = serializers.SerializerMethodField()
    selected_file = serializers.SerializerMethodField()

    class Meta:
        fields = FileSerializer.Meta.fields + (
            'content', 'entries', 'selected_file', 'download_url',
            'uses_unknown_minified_code'
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

    def _get_hash_for_selected_file(self, obj):
        selected_file = self.get_selected_file(obj)

        # Return the hash if we already saved it to the locally cached
        # `self._entries` dictionary.
        _entries = getattr(self, '_entries', {})

        if _entries and _entries[selected_file]['sha256']:
            return _entries[selected_file]['sha256']

        commit = self._get_commit(obj)
        tree = self.repo.get_root_tree(commit)

        # Normalize the key as we want to avoid that we exceed max
        # key lengh because of selected_file.
        cache_key = make_key(
            f'reviewers:fileentriesserializer:hashes'
            f':{commit.hex}:{selected_file}',
            with_locale=False,
            normalize=True)

        def _calculate_hash():
            try:
                blob_or_tree = tree[selected_file]
            except KeyError:
                return None

            if blob_or_tree.type == pygit2.GIT_OBJ_TREE:
                return None

            blob = self.git_repo[blob_or_tree.oid]
            return get_sha256(io.BytesIO(memoryview(blob)))

        return cache.get_or_set(cache_key, _calculate_hash, 60 * 60 * 24)

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

                commit_tzinfo = timezone(timedelta(
                    minutes=commit.commit_time_offset))
                commit_time = datetime.fromtimestamp(
                    float(commit.commit_time),
                    commit_tzinfo)

                mimetype, entry_mime_category = get_mime_type_for_blob(
                    tree_or_blob=entry.type, name=entry.name, blob=blob)

                result[path] = {
                    'depth': path.count(os.sep),
                    'filename': force_text(entry.name),
                    'sha256': None,
                    'mime_category': entry_mime_category,
                    'mimetype': mimetype,
                    'path': path,
                    'size': blob.size if blob is not None else None,
                    'modified': commit_time,
                }
            return result

        self._entries = cache.get_or_set(
            'reviewers:fileentriesserializer:entries:{}'.format(commit.hex),
            _fetch_entries,
            # Store information about this commit for 24h which should be
            # enough to cover regular review-times but not overflow our
            # cache
            60 * 60 * 24)

        # Fetch and set the sha hash for the currently selected file.
        sha256 = self._get_hash_for_selected_file(obj)
        self._entries[self.get_selected_file(obj)]['sha256'] = sha256

        return self._entries

    def get_selected_file(self, obj):
        requested_file = self.context.get('file', None)
        files = self.get_entries(obj)

        if requested_file is None:
            default_files = ('manifest.json', 'install.rdf', 'package.json')

            for manifest in default_files:
                if manifest in files:
                    requested_file = manifest
                    break
            else:
                # This could be a search engine
                requested_file = list(files.keys())[0]

        if requested_file not in files:
            raise NotFound('File not found')

        return requested_file

    def get_content(self, obj):
        commit = self._get_commit(obj)
        tree = self.repo.get_root_tree(commit)
        selected_file = self.get_selected_file(obj)
        blob_or_tree = tree[selected_file]

        if blob_or_tree.type == pygit2.GIT_OBJ_BLOB:
            blob = self.git_repo[blob_or_tree.oid]
            mimetype, mime_category = get_mime_type_for_blob(
                tree_or_blob='blob', name=blob_or_tree.name, blob=blob)

            # Only return the raw data if we detect a file that contains text
            # data that actually can be rendered.
            if mime_category == 'text':
                # Remove any BOM data if preset.
                return unicodehelper.decode(blob.read_raw())

        # By default return an empty string.
        # See https://github.com/mozilla/addons-server/issues/11782 for
        # more explanation.
        return ''

    def get_uses_unknown_minified_code(self, obj):
        try:
            validation = obj.validation
        except FileValidation.DoesNotExist:
            # We don't have any idea about whether it could be minified or not
            # so let's assume it's not for now.
            return False

        validation_data = json.loads(validation.validation)

        prop = 'unknownMinifiedFiles'
        minified_files = validation_data.get('metadata', {}).get(prop, [])
        return self.get_selected_file(obj) in minified_files

    def get_download_url(self, obj):
        commit = self._get_commit(obj)
        tree = self.repo.get_root_tree(commit)
        selected_file = self.get_selected_file(obj)

        try:
            blob_or_tree = tree[selected_file]
        except KeyError:
            # This can happen when the file has been deleted.
            return None

        if blob_or_tree.type == pygit2.GIT_OBJ_TREE:
            return None

        return absolutify(reverse(
            'reviewers.download_git_file',
            kwargs={
                'version_id': self.get_instance().version.pk,
                'filename': selected_file
            }
        ))


class MinimalVersionSerializerWithChannel(MinimalVersionSerializer):
    channel = ReverseChoiceField(
        choices=list(amo.CHANNEL_CHOICES_API.items()))

    class Meta:
        model = Version
        fields = ('id', 'channel', 'version')


class AddonBrowseVersionSerializer(MinimalVersionSerializerWithChannel):
    validation_url_json = serializers.SerializerMethodField()
    validation_url = serializers.SerializerMethodField()
    has_been_validated = serializers.SerializerMethodField()
    file = FileEntriesSerializer(source='current_file')
    addon = SimpleAddonSerializer()

    class Meta:
        model = Version
        fields = (
            # Bare minimum fields we need from parent...
            'id', 'channel', 'reviewed', 'version',
            # Plus our custom ones.
            'addon', 'file', 'has_been_validated', 'validation_url',
            'validation_url_json'
        )

    def get_validation_url_json(self, obj):
        return absolutify(reverse('devhub.json_file_validation', args=[
            obj.addon.slug, obj.current_file.id
        ]))

    def get_validation_url(self, obj):
        return absolutify(reverse('devhub.file_validation', args=[
            obj.addon.slug, obj.current_file.id
        ]))

    def get_has_been_validated(self, obj):
        return obj.current_file.has_been_validated


class DiffableVersionSerializer(MinimalVersionSerializerWithChannel):
    pass


class MinimalBaseFileSerializer(FileSerializer):
    class Meta:
        model = File
        fields = ('id',)


class FileEntriesDiffSerializer(FileEntriesSerializer):
    diff = serializers.SerializerMethodField()
    entries = serializers.SerializerMethodField()
    selected_file = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    uses_unknown_minified_code = serializers.SerializerMethodField()
    base_file = serializers.SerializerMethodField()

    class Meta:
        fields = FileSerializer.Meta.fields + (
            'diff', 'entries', 'selected_file', 'download_url',
            'uses_unknown_minified_code', 'base_file'
        )
        model = File

    def get_diff(self, obj):
        commit = obj.version.git_hash
        parent = self.context['parent_version'].git_hash

        # Initial commits have both set to the same version
        parent = parent if parent != commit else None

        diff = self.repo.get_diff(
            commit=commit,
            parent=parent,
            pathspec=[self.get_selected_file(obj)])

        # Because we're always specifying `pathspec` with the currently
        # selected file we can inline the diff because there will always be
        # one.
        # See: https://github.com/mozilla/addons-server/issues/11392
        return next(iter(diff), None)

    def get_entries(self, obj):
        """Overwrite `FileEntriesSerializer.get_entries to inject

        added/removed/changed information.
        """
        commit = obj.version.git_hash
        parent = self.context['parent_version'].git_hash

        # Initial commits have both set to the same version
        parent = parent if parent != commit else None

        deltas = self.repo.get_deltas(
            commit=commit,
            parent=parent,
            pathspec=None)

        entries = super().get_entries(obj)

        # All files have a "unmodified" status by default
        for path, value in entries.items():
            entries[path].setdefault('status', '')

        # Now let's overwrite that with data from the actual delta
        for delta in deltas:
            path = delta['path']

            path_depth = path.count(os.sep)
            path_deleted = False
            if path not in entries:
                # The file got deleted so let's mimic the original data-
                # structure for better modeling on the client.
                # Most of the actual data is not present, though, so we set
                # it to `None`.
                path_deleted = True
                filename = os.path.basename(path)
                mime, _ = mimetypes.guess_type(filename)
                entries[path] = {
                    'depth': path_depth,
                    'filename': filename,
                    'sha256': None,
                    'mime_category': None,
                    'mimetype': mime,
                    'path': path,
                    'size': None,
                    'modified': None,
                }

            # Now we can set the git-status.
            entries[path]['status'] = delta['mode']

            for index, parent in enumerate(pathlib.Path(path).parents):
                parent = str(parent)

                if (
                    path_deleted is True and
                    parent != '.' and
                    parent not in entries
                ):
                    # The parent directory of this deleted file does not
                    # exist. This could happen if no other files were
                    # modified within the directory.
                    entries[parent] = {
                        'depth': path_depth - 1 - index,
                        'filename': os.path.basename(parent),
                        'sha256': None,
                        'mime_category': 'directory',
                        'mimetype': 'application/octet-stream',
                        'path': parent,
                        'size': None,
                        'modified': None,
                    }

        return entries

    def get_uses_unknown_minified_code(self, obj):
        parent = self.context['parent_version']
        selected_file = self.get_selected_file(obj)

        for file in [parent.current_file, obj]:
            try:
                data = json.loads(file.validation.validation)
            except FileValidation.DoesNotExist:
                continue

            prop = 'unknownMinifiedFiles'
            minified_files = data.get('metadata', {}).get(prop, [])
            if selected_file in minified_files:
                return True
        return False

    def get_base_file(self, obj):
        # We can't directly use `source=` in the file definitions above
        # because the parent version gets passed through the `context`
        base_file = self.context['parent_version'].current_file
        return MinimalBaseFileSerializer(instance=base_file).data


class AddonCompareVersionSerializer(AddonBrowseVersionSerializer):
    file = FileEntriesDiffSerializer(source='current_file')

    class Meta(AddonBrowseVersionSerializer.Meta):
        pass


class CannedResponseSerializer(serializers.ModelSerializer):
    # Title is actually more fitting than the internal "name"
    title = serializers.CharField(source='name')
    category = serializers.SerializerMethodField()

    class Meta:
        model = CannedResponse
        fields = ('id', 'title', 'response', 'category')

    def get_category(self, obj):
        return amo.CANNED_RESPONSE_CATEGORY_CHOICES[obj.category]


class DraftCommentSerializer(serializers.ModelSerializer):
    user = SplitField(
        serializers.PrimaryKeyRelatedField(queryset=UserProfile.objects.all()),
        BaseUserSerializer())
    version = SplitField(
        serializers.PrimaryKeyRelatedField(
            queryset=Version.unfiltered.all()),
        AddonBrowseVersionSerializer())
    canned_response = SplitField(
        serializers.PrimaryKeyRelatedField(
            queryset=CannedResponse.objects.all(),
            required=False),
        CannedResponseSerializer(),
        allow_null=True,
        required=False)

    class Meta:
        model = DraftComment
        fields = (
            'id', 'filename', 'lineno', 'comment',
            'version', 'user', 'canned_response'
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set the instance for `AddonBrowseVersionSerializer` which requires
        # on `instance` being set correctly.
        self.fields['version'].output.instance = self.context['version']

    def get_or_default(self, key, data, default=''):
        """Return the value of ``key`` in ``data``

        If that key is not present then return the value of ``key`` from
        ``self.instance`, otherwise return the ``default``.

        This method is a helper to simplify validation for partial updates.
        """
        retval = data.get(key)

        if retval is None and self.instance is not None:
            retval = getattr(self.instance, key)

        return retval or default

    def validate(self, data):
        canned_response = self.get_or_default('canned_response', data)
        comment = self.get_or_default('comment', data)

        if comment and canned_response:
            raise serializers.ValidationError(
                {'comment': ugettext(
                    'You can\'t submit a comment if `canned_response` is '
                    'defined.')})

        if not canned_response and not comment:
            raise serializers.ValidationError(
                {'comment': ugettext(
                    'You can\'t submit an empty comment.')})

        lineno = self.get_or_default('lineno', data)
        filename = self.get_or_default('filename', data)

        if lineno and not filename:
            raise serializers.ValidationError(
                {'comment': ugettext(
                    'You can\'t submit a line number without associating '
                    'it to a filename.')})
        return data
