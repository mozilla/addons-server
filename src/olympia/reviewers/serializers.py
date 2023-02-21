import hashlib
import io
import os
import mimetypes
import pathlib
import json
from collections import OrderedDict

import pygit2

from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.reverse import reverse as drf_reverse

from django.core.cache import cache
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.encoding import force_bytes, force_str

from olympia import amo
from olympia.activity.models import DraftComment
from olympia.accounts.serializers import BaseUserSerializer
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.addons.serializers import (
    FileSerializer,
    MinimalVersionSerializer,
    SimpleAddonSerializer,
)
from olympia.addons.models import AddonReviewerFlags
from olympia.api.fields import ReverseChoiceField, SplitField
from olympia.api.serializers import AMOModelSerializer
from olympia.users.models import UserProfile
from olympia.files.utils import get_sha256
from olympia.files.models import File, FileValidation
from olympia.versions.models import Version
from olympia.git.utils import AddonGitRepository, get_mime_type_for_blob
from olympia.lib import unicodehelper


class AddonReviewerFlagsSerializer(AMOModelSerializer):
    class Meta:
        model = AddonReviewerFlags
        fields = (
            'auto_approval_delayed_until',
            'auto_approval_delayed_until_unlisted',
            'auto_approval_disabled',
            'auto_approval_disabled_unlisted',
            'auto_approval_disabled_until_next_approval',
            'auto_approval_disabled_until_next_approval_unlisted',
            'needs_admin_code_review',
            'needs_admin_content_review',
            'needs_admin_theme_review',
        )

    def update(self, instance, validated_data):
        # Only update fields that changed. Note that this only supports basic
        # fields.
        if self.partial and instance:
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save(update_fields=validated_data.keys())
        else:
            instance = super().update(instance, validated_data)
        return instance


class FileEntriesMixin:
    def _get_version(self):
        """If neither the current instance nor the parent instance is a Version,
        check the context for a version, otherwise raise an exception."""
        if isinstance(self.instance, Version):
            return self.instance

        if self.parent is not None and isinstance(self.parent.instance, Version):
            return self.parent.instance

        version = self.context.get('version', None)
        if isinstance(version, Version):
            return version

        raise RuntimeError('This serialzer should not be created without a Version')

    @cached_property
    def repo(self):
        return AddonGitRepository(self._get_version().addon)

    @property
    def git_repo(self):
        return self.repo.git_repository

    @cached_property
    def commit(self):
        """Return the pygit2 repository instance, preselect correct channel."""
        # Caching the commit to avoid calling revparse_single many times.
        try:
            return self.git_repo.revparse_single(self._get_version().git_hash)
        except pygit2.InvalidSpecError:
            raise NotFound("Couldn't find the requested version in git-repository")

    @cached_property
    def tree(self):
        # Caching the tree to avoid calling get_root_tree many times.
        return self.repo.get_root_tree(self.commit)

    def _get_selected_file(self):
        requested_file = self.context.get('file', None)
        files = self._get_entries()

        if requested_file is None:
            default_files = ('manifest.json',)

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

    def _get_blob_for_selected_file(self):
        """Returns the blob and filename for the selected file.

        Returns (None, None) if the selected file is not a blob.
        """
        tree = self.tree
        selected_file = self._get_selected_file()
        if selected_file in tree:
            blob_or_tree = tree[selected_file]

            if blob_or_tree.type == pygit2.GIT_OBJ_BLOB:
                return (self.git_repo[blob_or_tree.oid], blob_or_tree.name)

        return (None, None)

    def _get_hash_for_selected_file(self):
        selected_file = self._get_selected_file()

        # Return the hash if we already saved it to the locally cached
        # `self._entries` dictionary.
        _entries = getattr(self, '_entries', {})

        if _entries and _entries[selected_file]['sha256']:
            return _entries[selected_file]['sha256']

        commit = self.commit
        blob, name = self._get_blob_for_selected_file()

        # Normalize the key as we want to avoid that we exceed max
        # key lengh because of selected_file.
        cache_key = force_str(
            hashlib.sha256(
                force_bytes(
                    'reviewers:fileentriesserializer:hashes'
                    f':{commit.hex}:{selected_file}',
                )
            ).hexdigest()
        )

        def _calculate_hash():
            if blob is None:
                return None

            return get_sha256(io.BytesIO(memoryview(blob)))

        return cache.get_or_set(cache_key, _calculate_hash, 60 * 60 * 24)

    def _get_entries(self):
        # Given that this is a very expensive operation we have a two-fold
        # cache, one that is stored on this instance for very-fast retrieval
        # to support other method calls on this serializer
        # and another that uses memcached for regular caching
        if hasattr(self, '_entries'):
            return self._entries

        commit = self.commit
        result = OrderedDict()

        def _fetch_entries():
            tree = self.tree

            for entry_wrapper in self.repo.iter_tree(tree):
                entry = entry_wrapper.tree_entry
                path = force_str(entry_wrapper.path)
                blob = entry_wrapper.blob

                mimetype, entry_mime_category = get_mime_type_for_blob(
                    tree_or_blob=entry.type, name=entry.name
                )

                result[path] = {
                    'depth': path.count(os.sep),
                    'filename': force_str(entry.name),
                    'sha256': None,
                    'mime_category': entry_mime_category,
                    'mimetype': mimetype,
                    'path': path,
                    'size': blob.size if blob is not None else None,
                }
            return result

        self._entries = cache.get_or_set(
            f'reviewers:fileentriesserializer:entries:{commit.hex}',
            _fetch_entries,
            # Store information about this commit for 24h which should be
            # enough to cover regular review-times but not overflow our
            # cache
            60 * 60 * 24,
        )

        # Fetch and set the sha hash for the currently selected file.
        sha256 = self._get_hash_for_selected_file()
        self._entries[self._get_selected_file()]['sha256'] = sha256

        return self._entries


class FileEntriesDiffMixin(FileEntriesMixin):
    def _get_entries(self):
        """Overwrite `FileEntriesMixin._get_entries to inject
        added/removed/changed information."""
        commit = self._get_version().git_hash
        parent = self.context['parent_version'].git_hash

        # Initial commits have both set to the same version
        parent = parent if parent != commit else None

        deltas = self.repo.get_deltas(commit=commit, parent=parent, pathspec=None)

        entries = super()._get_entries()

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
                }

            # Now we can set the git-status.
            entries[path]['status'] = delta['mode']

            for index, parent in enumerate(pathlib.Path(path).parents):
                parent = str(parent)

                if path_deleted is True and parent != '.' and parent not in entries:
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
                    }

        return entries


# NOTE: Because of caching, this serializer cannot be reused and must be
# created for each file. It cannot be used with DRF's many=True option.
class FileInfoSerializer(AMOModelSerializer, FileEntriesMixin):
    content = serializers.SerializerMethodField()
    uses_unknown_minified_code = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    selected_file = serializers.SerializerMethodField()
    mimetype = serializers.SerializerMethodField()
    sha256 = serializers.SerializerMethodField()
    size = serializers.SerializerMethodField()
    mime_category = serializers.SerializerMethodField()
    filename = serializers.SerializerMethodField()

    class Meta:
        fields = (
            'id',
            'content',
            'selected_file',
            'download_url',
            'uses_unknown_minified_code',
            'mimetype',
            'sha256',
            'size',
            'mime_category',
            'filename',
        )
        model = File

    def get_selected_file(self, obj):
        return self._get_selected_file()

    def get_mimetype(self, obj):
        entries = self._get_entries()
        return entries[self._get_selected_file()]['mimetype']

    def get_sha256(self, obj):
        return self._get_hash_for_selected_file()

    def get_size(self, obj):
        entries = self._get_entries()
        return entries[self._get_selected_file()]['size']

    def get_filename(self, obj):
        entries = self._get_entries()
        return entries[self._get_selected_file()]['filename']

    def get_mime_category(self, obj):
        entries = self._get_entries()
        return entries[self._get_selected_file()]['mime_category']

    def get_content(self, obj):
        blob, name = self._get_blob_for_selected_file()
        if blob is not None:
            mimetype, mime_category = get_mime_type_for_blob(
                tree_or_blob='blob', name=name
            )

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
        return self._get_selected_file() in minified_files

    def get_download_url(self, obj):
        selected_file = self._get_selected_file()
        blob, name = self._get_blob_for_selected_file()
        if blob is not None:
            return absolutify(
                reverse(
                    'reviewers.download_git_file',
                    kwargs={
                        'version_id': self._get_version().pk,
                        'filename': selected_file,
                    },
                )
            )

        return None


class MinimalVersionSerializerWithChannel(MinimalVersionSerializer):
    channel = ReverseChoiceField(choices=list(amo.CHANNEL_CHOICES_API.items()))

    class Meta:
        model = Version
        fields = ('id', 'channel', 'version')


class AddonBrowseVersionSerializerFileOnly(MinimalVersionSerializerWithChannel):
    file = FileInfoSerializer()

    class Meta:
        model = Version
        fields = ('id', 'file')


class AddonBrowseVersionSerializer(
    AddonBrowseVersionSerializerFileOnly, FileEntriesMixin
):
    validation_url_json = serializers.SerializerMethodField()
    validation_url = serializers.SerializerMethodField()
    has_been_validated = serializers.SerializerMethodField()
    file_entries = serializers.SerializerMethodField()
    addon = SimpleAddonSerializer()

    class Meta:
        model = Version
        fields = (
            'id',
            'channel',
            'reviewed',
            'version',
            'addon',
            'file',
            'has_been_validated',
            'validation_url',
            'validation_url_json',
            'file_entries',
        )

    def get_file_entries(self, obj):
        entries = self._get_entries()
        return self._trim_entries(entries)

    def _trim_entries(self, entries):
        result = OrderedDict()
        for value in entries.values():
            result[value['path']] = self._trim_entry(value)
        return result

    def _trim_entry(self, entry):
        return {
            key: entry[key]
            for key in ('depth', 'filename', 'mime_category', 'path', 'status')
            if key in entry
        }

    def get_validation_url_json(self, obj):
        return absolutify(
            drf_reverse(
                'reviewers-addon-json-file-validation',
                request=self.context.get('request'),
                args=[obj.addon.pk, obj.file.id],
            )
        )

    def get_validation_url(self, obj):
        return absolutify(
            reverse('devhub.file_validation', args=[obj.addon.pk, obj.file.id])
        )

    def get_has_been_validated(self, obj):
        return obj.file.has_been_validated

    def get_reviewed(self, obj):
        return serializers.DateTimeField().to_representation(
            obj.file.approval_date or obj.human_review_date
        )


class DiffableVersionSerializer(MinimalVersionSerializerWithChannel):
    pass


class MinimalBaseFileSerializer(FileSerializer):
    class Meta:
        model = File
        fields = ('id',)


class FileInfoDiffSerializer(FileInfoSerializer, FileEntriesDiffMixin):
    diff = serializers.SerializerMethodField()
    selected_file = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    uses_unknown_minified_code = serializers.SerializerMethodField()
    base_file = serializers.SerializerMethodField()

    class Meta:
        fields = (
            'id',
            'diff',
            'selected_file',
            'download_url',
            'uses_unknown_minified_code',
            'base_file',
            'sha256',
            'size',
            'mimetype',
            'mime_category',
            'filename',
        )
        model = File

    def get_diff(self, obj):
        commit = self._get_version().git_hash
        parent = self.context['parent_version'].git_hash

        # Initial commits have both set to the same version
        parent = parent if parent != commit else None

        diff = self.repo.get_diff(
            commit=commit, parent=parent, pathspec=[self._get_selected_file()]
        )

        # Because we're always specifying `pathspec` with the currently
        # selected file we can inline the diff because there will always be
        # one.
        # See: https://github.com/mozilla/addons-server/issues/11392
        return next(iter(diff), None)

    def get_uses_unknown_minified_code(self, obj):
        parent = self.context['parent_version']
        selected_file = self._get_selected_file()

        for file in [parent.file, obj]:
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
        base_file = self.context['parent_version'].file
        return MinimalBaseFileSerializer(instance=base_file).data


class AddonCompareVersionSerializerFileOnly(AddonBrowseVersionSerializer):
    file = FileInfoDiffSerializer()

    class Meta:
        model = Version
        fields = ('id', 'file')


class AddonCompareVersionSerializer(
    AddonCompareVersionSerializerFileOnly, FileEntriesDiffMixin
):
    class Meta(AddonBrowseVersionSerializer.Meta):
        pass


class DraftCommentSerializer(AMOModelSerializer):
    user = SplitField(
        serializers.PrimaryKeyRelatedField(queryset=UserProfile.objects.all()),
        BaseUserSerializer(),
    )
    version_id = serializers.PrimaryKeyRelatedField(
        queryset=Version.unfiltered.all(), source='version'
    )

    class Meta:
        model = DraftComment
        fields = (
            'id',
            'filename',
            'lineno',
            'comment',
            'version_id',
            'user',
        )

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
        comment = self.get_or_default('comment', data)

        if not comment:
            raise serializers.ValidationError(
                {'comment': "You can't submit an empty comment."}
            )

        lineno = self.get_or_default('lineno', data)
        filename = self.get_or_default('filename', data)

        if lineno and not filename:
            raise serializers.ValidationError(
                {
                    'comment': (
                        "You can't submit a line number without associating "
                        'it to a filename.'
                    )
                }
            )
        return data
