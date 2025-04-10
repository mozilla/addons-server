from tests import TestCase
from unittest.mock import patch

from scripts.create_release import main, create_release_notes

class BaseTestCase(TestCase):
    def setUp(self):
        self.previous_version = '2025.04.09'
        self.major_version = '2025.04.10'
        self.minor_version = f'{self.major_version}.1'
        self.minor_version_next = f'{self.major_version}.2'

        patch_get_release = patch('scripts.create_release.get_release')
        self.mock_get_release = patch_get_release.start()
        self.mock_get_release.return_value = None
        self.addCleanup(patch_get_release.stop)

        path_get_commit = patch('scripts.create_release.get_commit')
        self.mock_get_commit = path_get_commit.start()
        self.addCleanup(path_get_commit.stop)

        patch_create_release = patch('scripts.create_release.create_release')
        self.mock_create_release = patch_create_release.start()
        self.addCleanup(patch_create_release.stop)

    def release_version(self, tag, author):
        return {
            'tag_name': tag,
            'author': {
                'login': author,
            },
            'html_url': f'https://github.com/test-user/test-repo/releases/tag/{tag}',
        }

    def commit(self, sha, author):
        return {
            'sha': sha,
            'author': {
                'login': author,
            },
            'commit': {
                'message': 'test commit',
            },
            'html_url': f'https://github.com/test-user/test-repo/commit/{sha}',
        }

class TestCreateReleaseNotes(BaseTestCase):
    def test_release_notes(self):
        self.assertMatchesJsonSnapshot(
            create_release_notes(
                self.major_version,
                'test-user',
                self.release_version(self.previous_version, 'test-user'),
                [],
            )
        )

    def test_release_notes_cherry_picks(self):
        self.mock_get_commit.return_value = self.commit('foo', 'test-user')

        self.assertMatchesJsonSnapshot(
            create_release_notes(
                self.major_version,
                'test-user',
                self.release_version(self.previous_version, 'test-user'),
                ['foo'],
            )
        )


class TestCreateRelease(BaseTestCase):
    def test_create_release_missing_version(self):
        with self.assertRaises(ValueError):
            main(None, None, False, [])

    def test_create_release_invalid_version(self):
        for version in ['foo', '2025/04/10', '2025.04.10.1']:
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    main(version, None, False, [])

    def test_create_release_major_already_exists(self):
        self.mock_get_release.return_value = self.release_version(
            self.major_version, 'test-user'
        )
        with self.assertRaises(
            ValueError, msg=f'Major version {self.major_version} already exists'
        ):
            main(self.major_version, None, False, [])

    def test_create_release_major_no_author(self):
        with self.assertRaises(
            ValueError, msg=(
                f'Cannot create major release {self.major_version} because no author is provided.'
            )
        ):
            main(self.major_version, None, False, [])

    def test_create_release_major_success(self):
        previous_author = 'prev-user'
        current_author = 'current-user'
        previous_release = self.release_version(self.previous_version, previous_author)
        def mock_get_release(version = None):
            if version is None or version == self.previous_version:
                return previous_release
            return None

        self.mock_get_release.side_effect = mock_get_release
        main(self.major_version, current_author, False, [])
        self.mock_create_release.assert_called_once_with(
            self.major_version,
            current_author,
            previous_release,
            [],
        )

    def test_create_release_minor_invalid_major(self):
        with self.assertRaises(ValueError):
            main(self.major_version, None, True, [])

    def test_create_release_minor_no_cherry_picks(self):
        with self.assertRaises(
            ValueError, msg=(
                f'Cannot create minor release {self.minor_version} because no cherry picks are provided.'
            )
        ):
            main(self.major_version, None, True, [])

    def test_create_release_minor_cherry_picks_invalid(self):
        with self.assertRaises(ValueError, msg='wow'):
            main(self.major_version, None, True, ['foo'])

    def test_create_release_minor_without_previous_minor(self):
        major_release = self.release_version(self.major_version, 'test-user')
        def mock_get_release(version):
            if version == self.major_version:
                return major_release
            return None

        self.mock_get_release.side_effect = mock_get_release

        def mock_get_commit(owner, repo, sha):
            return self.commit(sha, 'test-user')

        self.mock_get_commit.side_effect = mock_get_commit
        main(self.major_version, None, True, ['foo'])
        self.mock_create_release.assert_called_once_with(
            self.minor_version,
            None,
            major_release,
            ['foo'],
        )

    def test_create_release_minor_with_previous_minor(self):
        major_release = self.release_version(self.major_version, 'test-user')
        previous_release = self.release_version(self.previous_version, 'test-user')
        previous_minor_release = self.release_version(self.minor_version, 'test-user')

        def mock_get_release(version):
            if version == self.major_version:
                return major_release
            elif version == self.minor_version:
                return previous_minor_release
            elif version == self.minor_version_next:
                return None
            return previous_release

        self.mock_get_release.side_effect = mock_get_release

        def mock_get_commit(owner, repo, sha):
            return self.commit(sha, 'test-user')

        self.mock_get_commit.side_effect = mock_get_commit

        main(self.major_version, 'test-user', True, ['foo'])
        self.mock_create_release.assert_called_once_with(
            self.minor_version_next,
            'test-user',
            previous_minor_release,
            ['foo'],
        )
