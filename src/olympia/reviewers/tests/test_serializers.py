import json

from django.core.cache import cache
from django.urls import reverse

from rest_framework.exceptions import NotFound
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from olympia.activity.models import DraftComment
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    reverse_ns,
    user_factory,
    version_factory,
)
from olympia.files.models import FileValidation
from olympia.git.utils import AddonGitRepository, extract_version_to_git
from olympia.git.tests.test_utils import apply_changes
from olympia.reviewers.serializers import (
    AddonBrowseVersionSerializer,
    AddonBrowseVersionSerializerFileOnly,
    AddonCompareVersionSerializerFileOnly,
    AddonCompareVersionSerializer,
    DraftCommentSerializer,
    FileInfoDiffSerializer,
    FileInfoSerializer,
)
from olympia.versions.models import License


class TestFileInfoSerializer(TestCase):
    def setUp(self):
        super().setUp()

        self.addon = addon_factory(file_kw={'filename': 'notify-link-clicks-i18n.xpi'})
        extract_version_to_git(self.addon.current_version.pk)
        self.addon.current_version.refresh_from_db()

        extract_version_to_git(self.addon.current_version.pk)
        self.addon.current_version.reload()
        assert self.addon.current_version.file.file.name
        self.version = self.addon.current_version
        self.file = self.addon.current_version.file

        # Set up the request to support drf_reverse
        api_version = api_settings.DEFAULT_VERSION
        self.request = APIRequestFactory().get('/api/%s/' % api_version)
        self.request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
        self.request.version = api_version

    def get_serializer(self, **extra_context):
        extra_context.setdefault('version', self.version)
        extra_context['request'] = self.request

        return FileInfoSerializer(instance=self.file, context=extra_context)

    def serialize(self, **extra_context):
        return self.get_serializer(**extra_context).data

    def test_raises_without_version(self):
        file = self.addon.current_version.file
        serializer = FileInfoSerializer(instance=file)

        with self.assertRaises(RuntimeError):
            serializer.data

    def test_can_access_version_from_parent(self):
        serializer = AddonBrowseVersionSerializer(
            instance=self.addon.current_version, context={'request': self.request}
        )
        file = serializer.data['file']
        assert file['id'] == self.addon.current_version.file.pk

    def test_basic(self):
        expected_file_type = 'text'
        expected_filename = 'manifest.json'
        expected_mimetype = 'application/json'
        expected_sha256 = (
            '71d4122c0f2f78e089136602f88dbf590f2fa04bb5bc417454bf21446d6cb4f0'
        )
        expected_size = 622

        data = self.serialize()

        assert data['id'] == self.addon.current_version.file.pk
        assert data['selected_file'] == 'manifest.json'
        assert data['download_url'] == absolutify(
            reverse(
                'reviewers.download_git_file',
                kwargs={
                    'version_id': self.addon.current_version.pk,
                    'filename': 'manifest.json',
                },
            )
        )
        assert not data['uses_unknown_minified_code']
        assert data['mimetype'] == expected_mimetype
        assert data['sha256'] == expected_sha256
        assert data['size'] == expected_size
        assert data['mime_category'] == expected_file_type
        assert data['filename'] == expected_filename

        assert '"manifest_version": 2' in data['content']
        assert 'id": "notify-link-clicks-i18n@notzilla.org' in data['content']

    def test_requested_file(self):
        data = self.serialize(file='icons/LICENSE')

        assert data['id'] == self.addon.current_version.file.pk
        assert data['selected_file'] == 'icons/LICENSE'
        assert data['content'].startswith(
            'The "link-48.png" icon is taken from the Geomicons'
        )
        assert data['download_url'] == absolutify(
            reverse(
                'reviewers.download_git_file',
                kwargs={
                    'version_id': self.addon.current_version.pk,
                    'filename': 'icons/LICENSE',
                },
            )
        )
        assert data['mimetype'] == 'text/plain'
        assert data['sha256'] == (
            'b48e66c02fe62dd47521def7c5ea11b86af91b94c23cfdf67592e1053952ed55'
        )
        assert data['size'] == 136
        assert data['mime_category'] == 'text'
        assert data['filename'] == 'LICENSE'

    def test_requested_file_with_non_existent_file(self):
        with self.assertRaises(NotFound):
            self.serialize(file='UNKNOWN_FILE')

    def test_dont_render_content_binary_file(self):
        data = self.serialize(file='icons/link-48.png')
        assert data['content'] == ''

    def test_uses_unknown_minified_code(self):
        validation_data = {'metadata': {'unknownMinifiedFiles': ['content-script.js']}}

        fobj = self.addon.current_version.file

        FileValidation.objects.create(file=fobj, validation=json.dumps(validation_data))

        data = self.serialize(file='content-script.js')
        assert data['uses_unknown_minified_code']

        data = self.serialize(file='background-script.js')
        assert not data['uses_unknown_minified_code']


class TestFileInfoDiffSerializer(TestCase):
    def setUp(self):
        super().setUp()

        self.addon = addon_factory(
            name='My Addôn',
            slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

        extract_version_to_git(self.addon.current_version.pk)
        self.addon.current_version.refresh_from_db()
        self.version = self.addon.current_version
        self.file = self.addon.current_version.file

        # Set up the request to support drf_reverse
        api_version = api_settings.DEFAULT_VERSION
        self.request = APIRequestFactory().get('/api/%s/' % api_version)
        self.request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
        self.request.version = api_version

    def get_serializer(self, **extra_context):
        extra_context.setdefault('version', self.version)
        extra_context['request'] = self.request

        return FileInfoDiffSerializer(instance=self.file, context=extra_context)

    def serialize(self, **extra_context):
        return self.get_serializer(**extra_context).data

    def test_raises_without_version(self):
        file = self.addon.current_version.file
        serializer = FileInfoDiffSerializer(instance=file)

        with self.assertRaises(RuntimeError):
            serializer.data

    def test_can_access_version_from_parent(self):
        parent_version = self.addon.current_version

        new_version = version_factory(
            addon=self.addon,
            file_kw={
                'filename': 'webextension_no_id.xpi',
            },
        )

        AddonGitRepository.extract_and_commit_from_version(new_version)

        serializer = AddonCompareVersionSerializer(
            instance=new_version,
            context={'parent_version': parent_version, 'request': self.request},
        )
        file = serializer.data['file']
        assert file['id'] == new_version.file.pk

    def test_basic(self):
        expected_file_type = 'text'
        expected_filename = 'manifest.json'
        expected_mimetype = 'application/json'
        expected_sha256 = (
            'b634285d4b20bf6b198b2b2897c78b8e2c6eb39c92759025e338a14d18478dcb'
        )
        expected_size = 698

        parent_version = self.addon.current_version

        new_version = version_factory(
            addon=self.addon,
            file_kw={
                'filename': 'webextension_no_id.xpi',
            },
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        apply_changes(repo, new_version, 'Updated test file\n', 'test.txt')
        apply_changes(repo, new_version, '', 'README.md', delete=True)

        self.version = new_version
        self.file = new_version.file
        data = self.serialize(parent_version=parent_version)

        assert data['id'] == new_version.file.pk
        assert data['base_file'] == {'id': parent_version.file.pk}
        assert data['selected_file'] == 'manifest.json'
        assert data['download_url'] == absolutify(
            reverse(
                'reviewers.download_git_file',
                kwargs={
                    'version_id': self.addon.current_version.pk,
                    'filename': 'manifest.json',
                },
            )
        )
        assert not data['uses_unknown_minified_code']
        assert data['mimetype'] == expected_mimetype
        assert data['sha256'] == expected_sha256
        assert data['size'] == expected_size
        assert data['mime_category'] == expected_file_type
        assert data['filename'] == expected_filename

        # The API always renders a diff, even for unmodified files.
        assert data['diff'] is not None

    def test_serialize_deleted_file(self):
        expected_filename = 'manifest.json'
        parent_version = self.addon.current_version
        new_version = version_factory(
            addon=self.addon,
            file_kw={
                'filename': 'webextension_no_id.xpi',
            },
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)
        apply_changes(repo, new_version, '', expected_filename, delete=True)

        self.version = new_version
        self.file = new_version.file
        data = self.serialize(parent_version=parent_version)

        assert data['download_url'] is None
        # We deleted the selected file, so there should be a diff.
        assert data['diff'] is not None
        assert data['diff']['mode'] == 'D'
        assert data['mimetype'] == 'application/json'
        assert data['sha256'] is None
        assert data['size'] is None
        assert data['mime_category'] is None
        assert data['filename'] == expected_filename

    def test_selected_file_unmodified(self):
        parent_version = self.addon.current_version

        new_version = version_factory(
            addon=self.addon,
            file_kw={
                'filename': 'webextension_no_id.xpi',
            },
        )
        AddonGitRepository.extract_and_commit_from_version(new_version)

        self.version = new_version
        self.file = new_version.file
        data = self.serialize(parent_version=parent_version)

        assert data['id'] == self.addon.current_version.file.pk
        assert data['filename'] == 'manifest.json'
        assert data['diff'] is not None

    def test_uses_unknown_minified_code(self):
        parent_version = self.addon.current_version

        new_version = version_factory(
            addon=self.addon,
            file_kw={
                'filename': 'webextension_no_id.xpi',
            },
        )
        AddonGitRepository.extract_and_commit_from_version(new_version)

        validation_data = {'metadata': {'unknownMinifiedFiles': ['README.md']}}

        # Let's create a validation for the parent but not the current file
        # which will result in us notifying the frontend of a minified file
        # as well
        current_validation = FileValidation.objects.create(
            file=parent_version.file, validation=json.dumps(validation_data)
        )

        self.version = new_version
        self.file = new_version.file
        data = self.serialize(parent_version=parent_version, file='README.md')
        assert data['uses_unknown_minified_code']

        data = self.serialize(parent_version=parent_version, file='manifest.json')
        assert not data['uses_unknown_minified_code']

        current_validation.delete()

        # Creating a validation object for the current one works as well
        FileValidation.objects.create(
            file=self.version.file, validation=json.dumps(validation_data)
        )

        data = self.serialize(parent_version=parent_version, file='README.md')
        assert data['uses_unknown_minified_code']

        data = self.serialize(parent_version=parent_version, file='manifest.json')
        assert not data['uses_unknown_minified_code']


class TestAddonBrowseVersionSerializerFileOnly(TestCase):
    def setUp(self):
        super().setUp()

        self.addon = addon_factory(file_kw={'filename': 'notify-link-clicks-i18n.xpi'})

        extract_version_to_git(self.addon.current_version.pk)
        self.addon.current_version.reload()
        self.version = self.addon.current_version

    def get_serializer(self, **extra_context):
        return AddonBrowseVersionSerializerFileOnly(
            instance=self.version, context=extra_context
        )

    def serialize(self, **extra_context):
        return self.get_serializer(**extra_context).data

    def test_basic(self):
        data = self.serialize()
        assert data['id'] == self.version.pk
        assert 'file' in data
        assert len(data.keys()) == 2


class TestAddonBrowseVersionSerializer(TestCase):
    def setUp(self):
        super().setUp()

        license = License.objects.create(
            name={
                'en-US': 'My License',
                'fr': 'Mä Licence',
            },
            text={
                'en-US': 'Lorem ipsum dolor sit amet, has nemore patrioqué',
            },
        )

        self.addon = addon_factory(
            file_kw={
                'hash': 'fakehash',
                'is_mozilla_signed_extension': True,
                'size': 42,
                'filename': 'notify-link-clicks-i18n.xpi',
            },
            version_kw={
                'license': license,
                'min_app_version': '50.0',
                'max_app_version': '*',
                'release_notes': {
                    'en-US': 'Release notes in english',
                    'fr': 'Notes de version en français',
                },
                'human_review_date': self.days_ago(0),
            },
        )

        extract_version_to_git(self.addon.current_version.pk)
        self.addon.current_version.reload()
        assert self.addon.current_version.release_notes
        self.version = self.addon.current_version

        # Set up the request to support drf_reverse
        api_version = api_settings.DEFAULT_VERSION
        self.request = APIRequestFactory().get('/api/%s/' % api_version)
        self.request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
        self.request.version = api_version

    def get_serializer(self, **extra_context):
        extra_context['request'] = self.request
        return AddonBrowseVersionSerializer(
            instance=self.version, context=extra_context
        )

    def serialize(self, **extra_context):
        return self.get_serializer(**extra_context).data

    def test_basic(self):
        data = self.serialize()
        assert data['id'] == self.version.pk

        assert data['channel'] == 'listed'
        assert data['reviewed'] == (
            self.version.human_review_date.replace(microsecond=0).isoformat() + 'Z'
        )

        # Custom fields
        validation_url_json = absolutify(
            reverse_ns(
                'reviewers-addon-json-file-validation',
                kwargs={'pk': self.addon.pk, 'file_id': self.version.file.id},
            )
        )
        validation_url = absolutify(
            reverse(
                'devhub.file_validation',
                args=[self.addon.pk, self.version.file.id],
            )
        )

        assert data['validation_url_json'] == validation_url_json
        assert data['validation_url'] == validation_url

        # That's been tested by TestFileEntriesSerializer
        assert 'file' in data

        assert data['has_been_validated'] is False

        assert dict(data['addon']) == {
            'id': self.addon.id,
            'slug': self.addon.slug,
            'name': {'en-US': self.addon.name},
            'icon_url': absolutify(self.addon.get_icon_url(64)),
        }

        assert set(data['file_entries'].keys()) == {
            'README.md',
            '_locales',
            '_locales/de',
            '_locales/en',
            '_locales/nb_NO',
            '_locales/nl',
            '_locales/ru',
            '_locales/sv',
            '_locales/ja',
            '_locales/de/messages.json',
            '_locales/en/messages.json',
            '_locales/ja/messages.json',
            '_locales/nb_NO/messages.json',
            '_locales/nl/messages.json',
            '_locales/ru/messages.json',
            '_locales/sv/messages.json',
            'background-script.js',
            'content-script.js',
            'icons',
            'icons/LICENSE',
            'icons/link-48.png',
            'manifest.json',
        }

        manifest_data = data['file_entries']['manifest.json']
        assert manifest_data['depth'] == 0
        assert manifest_data['filename'] == 'manifest.json'
        assert manifest_data['mime_category'] == 'text'
        assert manifest_data['path'] == 'manifest.json'

        ja_locale_data = data['file_entries']['_locales/ja']

        assert ja_locale_data['depth'] == 1
        assert ja_locale_data['mime_category'] == 'directory'
        assert ja_locale_data['filename'] == 'ja'
        assert ja_locale_data['path'] == '_locales/ja'

    def test_get_entries_cached(self):
        serializer = self.get_serializer()

        # start serialization
        data = serializer.data
        commit = serializer.commit

        assert serializer._trim_entries(serializer._entries) == data['file_entries']

        key = f'reviewers:fileentriesserializer:entries:{commit.hex}'
        cached_data = cache.get(key)

        # We exclude `manifest.json` here to test that in a separate step
        # because the sha256 calculation will overwrite `serializer._entries`
        # but doesn't update the cache (yet at least) to avoid cache
        # cache syncronisation issues
        expected_keys = {
            'README.md',
            '_locales',
            '_locales/de',
            '_locales/en',
            '_locales/nb_NO',
            '_locales/nl',
            '_locales/ru',
            '_locales/sv',
            '_locales/ja',
            '_locales/de/messages.json',
            '_locales/en/messages.json',
            '_locales/ja/messages.json',
            '_locales/nb_NO/messages.json',
            '_locales/nl/messages.json',
            '_locales/ru/messages.json',
            '_locales/sv/messages.json',
            'background-script.js',
            'content-script.js',
            'icons',
            'icons/LICENSE',
            'icons/link-48.png',
        }

        for key in expected_keys:
            assert serializer._trim_entry(cached_data[key]) == data['file_entries'][key]

    def test_sha256_only_calculated_or_fetched_for_selected_file(self):
        serializer = self.get_serializer(file='icons/LICENSE')
        serializer.data

        assert serializer._entries['manifest.json']['sha256'] is None
        assert serializer._entries['icons/LICENSE']['sha256'] == (
            'b48e66c02fe62dd47521def7c5ea11b86af91b94c23cfdf67592e1053952ed55'
        )

        serializer = self.get_serializer(file='manifest.json')
        serializer.data
        assert serializer._entries['manifest.json']['sha256'] == (
            '71d4122c0f2f78e089136602f88dbf590f2fa04bb5bc417454bf21446d6cb4f0'
        )
        assert serializer._entries['icons/LICENSE']['sha256'] is None


class TestAddonCompareVersionSerializerFileOnly(TestCase):
    def setUp(self):
        super().setUp()

        self.addon = addon_factory(file_kw={'filename': 'notify-link-clicks-i18n.xpi'})

        extract_version_to_git(self.addon.current_version.pk)
        self.addon.current_version.reload()
        self.version = self.addon.current_version

    def get_serializer(self, **extra_context):
        return AddonCompareVersionSerializerFileOnly(
            instance=self.version, context=extra_context
        )

    def serialize(self, **extra_context):
        return self.get_serializer(**extra_context).data

    def test_basic(self):
        parent_version = self.addon.current_version

        data = self.serialize(parent_version=parent_version)
        assert data['id'] == self.version.pk
        assert 'file' in data
        assert len(data.keys()) == 2


class TestAddonCompareVersionSerializer(TestCase):
    def setUp(self):
        super().setUp()

        self.addon = addon_factory(
            name='My Addôn',
            slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

        extract_version_to_git(self.addon.current_version.pk)
        self.addon.current_version.refresh_from_db()
        self.version = self.addon.current_version

        # Set up the request to support drf_reverse
        api_version = api_settings.DEFAULT_VERSION
        self.request = APIRequestFactory().get('/api/%s/' % api_version)
        self.request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
        self.request.version = api_version

    def create_new_version_for_addon(self, xpi_filename):
        addon = addon_factory(
            name='My Addôn',
            slug='my-addon',
            file_kw={'filename': xpi_filename},
        )

        extract_version_to_git(addon.current_version.pk)

        addon.current_version.refresh_from_db()
        parent_version = addon.current_version

        new_version = version_factory(
            addon=addon,
            file_kw={
                'filename': xpi_filename,
            },
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        return addon, repo, parent_version, new_version

    def get_serializer(self, **extra_context):
        extra_context['request'] = self.request
        return AddonCompareVersionSerializer(
            instance=self.version, context=extra_context
        )

    def serialize(self, **extra_context):
        return self.get_serializer(**extra_context).data

    def test_basic(self):
        expected_file_type = 'text'
        expected_filename = 'manifest.json'

        parent_version = self.addon.current_version

        new_version = version_factory(
            addon=self.addon,
            file_kw={
                'filename': 'webextension_no_id.xpi',
            },
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        apply_changes(repo, new_version, 'Updated test file\n', 'test.txt')
        apply_changes(repo, new_version, '', 'README.md', delete=True)

        self.version = new_version
        data = self.serialize(parent_version=parent_version)

        assert set(data['file_entries'].keys()) == {
            'manifest.json',
            'README.md',
            'test.txt',
        }

        # Unmodified file
        manifest_data = data['file_entries']['manifest.json']
        assert manifest_data['depth'] == 0
        assert manifest_data['filename'] == expected_filename
        assert manifest_data['mime_category'] == expected_file_type
        assert manifest_data['path'] == 'manifest.json'
        assert manifest_data['status'] == ''

        # Added a new file
        test_txt_data = data['file_entries']['test.txt']
        assert test_txt_data['depth'] == 0
        assert test_txt_data['filename'] == 'test.txt'
        assert test_txt_data['mime_category'] == 'text'
        assert test_txt_data['path'] == 'test.txt'
        assert test_txt_data['status'] == 'A'

        # Deleted file
        readme_data = data['file_entries']['README.md']
        assert readme_data['status'] == 'D'
        assert readme_data['depth'] == 0
        assert readme_data['filename'] == 'README.md'
        # Not testing mimetype as text/markdown is missing in CI mimetypes
        # database. But it doesn't matter much here since we're primarily
        # after the git status.
        assert readme_data['mime_category'] is None
        assert readme_data['path'] == 'README.md'

    def test_recreate_parent_dir_of_deleted_file(self):
        addon, repo, parent_version, new_version = self.create_new_version_for_addon(
            'webextension_signed_already.xpi'
        )

        apply_changes(repo, new_version, '', 'META-INF/mozilla.rsa', delete=True)

        self.version = new_version
        data = self.serialize(parent_version=parent_version)

        entries_by_file = {e['path']: e for e in data['file_entries'].values()}
        parent_dir = 'META-INF'
        assert parent_dir in entries_by_file.keys()

        parent = entries_by_file[parent_dir]
        assert parent['depth'] == 0
        assert parent['filename'] == parent_dir
        assert parent['mime_category'] == 'directory'
        assert parent['path'] == parent_dir

    def test_recreate_nested_parent_dir_of_deleted_file(self):
        addon, repo, parent_version, new_version = self.create_new_version_for_addon(
            'https-everywhere.xpi'
        )

        apply_changes(repo, new_version, '', '_locales/ru/messages.json', delete=True)

        self.version = new_version
        data = self.serialize(parent_version=parent_version)

        entries_by_file = {e['path']: e for e in data['file_entries'].values()}
        parent_dir = '_locales/ru'
        assert parent_dir in entries_by_file.keys()

        parent = entries_by_file[parent_dir]
        assert parent['depth'] == 1
        assert parent['filename'] == 'ru'
        assert parent['path'] == parent_dir

    def test_do_not_recreate_parent_dir_of_deleted_root_file(self):
        addon, repo, parent_version, new_version = self.create_new_version_for_addon(
            'webextension_signed_already.xpi'
        )

        apply_changes(repo, new_version, '', 'manifest.json', delete=True)

        self.version = new_version
        data = self.serialize(parent_version=parent_version)

        entries_by_file = {e['path']: e for e in data['file_entries'].values()}

        # Since we just deleted a root file, no additional entries
        # should have been added for its parent directory.
        assert list(sorted(entries_by_file.keys())) == [
            'META-INF',
            'META-INF/mozilla.rsa',
            'index.js',
            'manifest.json',
        ]

    def test_do_not_recreate_parent_dir_if_it_exists(self):
        addon, repo, parent_version, new_version = self.create_new_version_for_addon(
            'https-everywhere.xpi'
        )

        # Delete a file within a directory but modify another file.
        # This will preserve the directory, i.e. we won't have to
        # recreate it.
        apply_changes(
            repo, new_version, '', 'chrome-resources/css/chrome_shared.css', delete=True
        )
        apply_changes(
            repo, new_version, '/* new content */', 'chrome-resources/css/widgets.css'
        )

        self.version = new_version
        data = self.serialize(parent_version=parent_version)

        entries_by_file = {e['path']: e for e in data['file_entries'].values()}
        parent_dir = 'chrome-resources/css'
        assert parent_dir in entries_by_file.keys()

        parent = entries_by_file[parent_dir]
        assert parent['mime_category'] == 'directory'
        assert parent['path'] == parent_dir

    def test_expose_grandparent_dir_deleted_subfolders(self):
        addon, repo, parent_version, new_version = self.create_new_version_for_addon(
            'deeply-nested.zip'
        )

        apply_changes(repo, new_version, '', 'chrome/icons/de/foo.png', delete=True)

        self.version = new_version
        data = self.serialize(parent_version=parent_version)

        entries_by_file = {e['path']: e for e in data['file_entries'].values()}
        # Check that we correctly include grand-parent folders too
        # See https://github.com/mozilla/addons-server/issues/13092
        grandparent_dir = 'chrome'
        assert grandparent_dir in entries_by_file.keys()

        parent = entries_by_file[grandparent_dir]
        assert parent['mime_category'] == 'directory'
        assert parent['path'] == grandparent_dir
        assert parent['depth'] == 0


class TestDraftCommentSerializer(TestCase):
    def test_basic(self):
        addon = addon_factory()
        comment_text = 'Some comment'
        filename = 'somefile.js'
        lineno = 19
        user = user_factory()
        comment = DraftComment.objects.create(
            comment=comment_text,
            filename=filename,
            lineno=lineno,
            user=user,
            version=addon.current_version,
        )

        data = DraftCommentSerializer(instance=comment).data

        assert data['comment'] == comment_text
        assert data['filename'] == filename
        assert data['id'] == comment.id
        assert data['lineno'] == lineno
        assert data['user']['id'] == user.id
        assert data['version_id'] == addon.current_version.id
