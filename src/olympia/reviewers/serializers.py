import io
import os
import mimetypes
from collections import OrderedDict
from datetime import datetime

import pygit2
import magic

from rest_framework import serializers
from rest_framework.exceptions import NotFound

from django.utils.functional import cached_property
from django.utils.encoding import force_text
from django.utils.timezone import FixedOffset

from olympia import amo
from olympia.activity.models import DraftComment
from olympia.amo.urlresolvers import reverse
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.addons.serializers import (
    VersionSerializer, FileSerializer, SimpleAddonSerializer)
from olympia.addons.models import AddonReviewerFlags
from olympia.files.utils import get_sha256
from olympia.files.models import File
from olympia.reviewers.models import CannedResponse
from olympia.versions.models import Version
from olympia.lib.git import AddonGitRepository
from olympia.lib import unicodehelper
from olympia.lib.cache import cache_get_or_set


# Sometime mimetypes get changed in libmagic so this is a (hopefully short)
# list of mappings from old -> new types so that we stay compatible
# with versions out there in the wild.
MIMETYPE_COMPAT_MAPPING = {
    # https://github.com/file/file/commit/cee2b49c
    'application/xml': 'text/xml',
    # Special case, for empty text files libmime reports
    # application/x-empty for empty plain text files
    # So, let's normalize this.
    'application/x-empty': 'text/plain',
    # See: https://github.com/mozilla/addons-server/issues/11382
    'image/svg': 'image/svg+xml',
    # See: https://github.com/mozilla/addons-server/issues/11383
    'image/x-ms-bmp': 'image/bmp',
    # See: https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types#textjavascript  # noqa
    'application/javascript': 'text/javascript',
}


# Some official mimetypes belong to the `text` category, even though their
# names don't include `text/`.
MIMETYPE_CATEGORY_MAPPING = {
    'application/json': 'text',
    'application/xml': 'text',
}


class AddonReviewerFlagsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AddonReviewerFlags
        fields = ('auto_approval_disabled', 'needs_admin_code_review',
                  'needs_admin_content_review', 'needs_admin_theme_review',
                  'pending_info_request')


class FileEntriesSerializer(FileSerializer):
    content = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    entries = serializers.SerializerMethodField()
    selected_file = serializers.SerializerMethodField()

    class Meta:
        fields = FileSerializer.Meta.fields + (
            'content', 'entries', 'selected_file', 'download_url'
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

                sha_hash = (
                    get_sha256(io.BytesIO(memoryview(blob)))
                    if not entry.type == 'tree' else '')

                commit_tzinfo = FixedOffset(commit.commit_time_offset)
                commit_time = datetime.fromtimestamp(
                    float(commit.commit_time),
                    commit_tzinfo)

                mimetype, entry_mime_category = self.get_entry_mime_type(
                    entry, blob)

                result[path] = {
                    'depth': path.count(os.sep),
                    'filename': force_text(entry.name),
                    'sha256': sha_hash,
                    'mime_category': entry_mime_category,
                    'mimetype': mimetype,
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

    def get_entry_mime_type(self, entry, blob):
        """Returns the mimetype and type category.

        The type category can be ``image``, ``directory``, ``text`` or
        ``binary``.
        """
        if entry.type == 'tree':
            return 'application/octet-stream', 'directory'

        # Hardcoding the maximum amount of bytes to read here
        # until https://github.com/ahupp/python-magic/commit/50e8c856
        # lands in a release and we can read that value from libmagic
        # We're only reading the needed amount of content from the file to
        # not exhaust/read the whole blob into memory again.
        bytes_ = io.BytesIO(memoryview(blob)).read(1048576)
        mimetype = magic.from_buffer(bytes_, mime=True)

        # Apply compatibility mappings
        mimetype = MIMETYPE_COMPAT_MAPPING.get(mimetype, mimetype)

        # Try to find a more accurate "textual" mimetype.
        if mimetype == 'text/plain':
            # Allow text mimetypes to be more specific for readable files.
            # `python-magic`/`libmagic` usually just returns plain/text but we
            # should use actual types like text/css or text/javascript.
            mimetype, _ = mimetypes.guess_type(entry.name)
            # Re-apply compatibility mappings since `guess_type()` might return
            # a completely different mimetype.
            mimetype = MIMETYPE_COMPAT_MAPPING.get(mimetype, mimetype)

        known_type_cagegories = ('image', 'text')
        default_type_category = 'binary'
        # If mimetype has an explicit category, use it.
        type_category = MIMETYPE_CATEGORY_MAPPING.get(
            mimetype, mimetype.split('/')[0]
        ) if mimetype else default_type_category

        return (mimetype, default_type_category if type_category not in
                known_type_cagegories else type_category)

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
        blob_or_tree = tree[self.get_selected_file(obj)]

        if blob_or_tree.type == 'blob':
            # TODO: Test if this is actually needed, historically it was
            # because files inside a zip could have any encoding but I'm not
            # sure if git unifies this to some degree (cgrebs)
            return unicodehelper.decode(
                self.git_repo[blob_or_tree.oid].read_raw())

    def get_download_url(self, obj):
        commit = self._get_commit(obj)
        tree = self.repo.get_root_tree(commit)
        selected_file = self.get_selected_file(obj)

        try:
            blob_or_tree = tree[selected_file]
        except KeyError:
            # This can happen when the file has been deleted.
            return None

        if blob_or_tree.type == 'tree':
            return None

        return absolutify(reverse(
            'reviewers.download_git_file',
            kwargs={
                'version_id': self.get_instance().version.pk,
                'filename': selected_file
            }
        ))


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
        return absolutify(reverse('devhub.json_file_validation', args=[
            obj.addon.slug, obj.current_file.id
        ]))

    def get_validation_url(self, obj):
        return absolutify(reverse('devhub.file_validation', args=[
            obj.addon.slug, obj.current_file.id
        ]))

    def get_has_been_validated(self, obj):
        return obj.current_file.has_been_validated


class DiffableVersionSerializer(VersionSerializer):

    class Meta:
        model = Version
        fields = ('id', 'channel', 'version')


class FileEntriesDiffSerializer(FileEntriesSerializer):
    diff = serializers.SerializerMethodField()
    entries = serializers.SerializerMethodField()
    selected_file = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        fields = FileSerializer.Meta.fields + (
            'diff', 'entries', 'selected_file', 'download_url'
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

        diff = self.repo.get_diff(
            commit=commit,
            parent=parent,
            pathspec=None)

        entries = super().get_entries(obj)

        # All files have a "unmodified" status by default
        for path, value in entries.items():
            entries[path].setdefault('status', '')

        # Now let's overwrite that with data from the actual patch
        for patch in diff:
            path = patch['path']

            path_depth = path.count(os.sep)
            path_deleted = False
            if path not in entries:
                # The file got deleted so let's mimic the original data-structure
                # for better modeling on the client.
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
            entries[path]['status'] = patch['mode']

            parent_path = os.path.dirname(path)
            if path_deleted and parent_path != '' and parent_path not in entries:
                # The parent directory of this deleted file does not
                # exist. This could happen if no other files were
                # modified within the directory.
                entries[parent_path] = {
                    'depth': path_depth - 1,
                    'filename': os.path.basename(parent_path),
                    'sha256': None,
                    'mime_category': 'directory',
                    'mimetype': 'application/octet-stream',
                    'path': parent_path,
                    'size': None,
                    'modified': None,
                }

        return entries


class AddonCompareVersionSerializer(AddonBrowseVersionSerializer):
    file = FileEntriesDiffSerializer(source='current_file')

    class Meta(AddonBrowseVersionSerializer.Meta):
        pass


class DraftCommentSerializer(serializers.ModelSerializer):

    class Meta:
        model = DraftComment
        fields = ('comments',)


class CannedResponseSerializer(serializers.ModelSerializer):
    # Title is actually more fitting than the internal "name"
    title = serializers.CharField(source='name')
    category = serializers.SerializerMethodField()

    class Meta:
        model = CannedResponse
        fields = ('id', 'title', 'response', 'category')

    def get_category(self, obj):
        return amo.CANNED_RESPONSE_CATEGORY_CHOICES[obj.category]
