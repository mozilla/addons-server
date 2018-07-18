import zipfile

from copy import deepcopy

from django import forms
from django.test.utils import override_settings

import mock

from olympia.amo.tests import AMOPaths, TestCase
from olympia.github.utils import GithubCallback, GithubRequest, rezip_file


example_root = 'https://api.github.com/repos/org/repo'
example_pull_request = {
    'pull_request': {
        'head': {
            'repo': {
                'archive_url': example_root + '/{archive_format}{/ref}',
                'statuses_url': example_root + '/statuses/{sha}',
                'pulls_url': example_root + '/pulls{/number}',
            },
            'sha': 'abc',
        },
        'number': 1,
    },
    'repository': {'commits_url': example_root + '/commits{/sha}'},
}


class TestGithub(TestCase):
    def test_github(self):
        form = GithubRequest(data=example_pull_request)
        assert form.is_valid(), form.errors
        assert (
            form.cleaned_data['status_url']
            == 'https://api.github.com/repos/org/repo/statuses/abc'
        )
        assert (
            form.cleaned_data['zip_url']
            == 'https://api.github.com/repos/org/repo/zipball/abc'
        )

    def test_invalid(self):
        example = deepcopy(example_pull_request)
        del example['pull_request']['head']
        form = GithubRequest(data=example)
        assert not form.is_valid()

    def test_url_wrong(self):
        example = deepcopy(example_pull_request)
        example['pull_request']['head']['repo'] = 'http://a.m.o'
        form = GithubRequest(data=example)
        assert not form.is_valid()


@override_settings(GITHUB_API_USER='key', GITHUB_API_TOKEN='token')
class GithubBaseTestCase(TestCase):
    def setUp(self):
        super(GithubBaseTestCase, self).setUp()
        patch = mock.patch('olympia.github.utils.requests', autospec=True)
        self.addCleanup(patch.stop)
        self.requests = patch.start()
        self.data = {
            'type': 'github',
            'status_url': 'https://github/status',
            'zip_url': 'https://github/zip',
            'sha': 'some:sha',
        }
        self.github = GithubCallback(self.data)

    def check_status(self, status, call=None, url=None, **kw):
        url = url or self.data['status_url']
        body = {'context': 'mozilla/addons-linter'}
        if status != 'comment':
            body['state'] = status

        body.update(**kw)
        if not call:
            call = self.requests.post.call_args_list
            if len(call) != 1:
                # If you don't specify a call to test, we'll get the last
                # one off the stack, if there's more than one, that's a
                # problem.
                raise AssertionError('More than one call to requests.post')
            call = call[0]
        assert call == mock.call(url, json=body, auth=('key', 'token'))


class TestCallback(GithubBaseTestCase):
    def test_create_not_github(self):
        with self.assertRaises(ValueError):
            GithubCallback({'type': 'bitbucket'})

    def test_pending(self):
        self.github.pending()
        self.check_status('pending')

    def test_success(self):
        self.github.success('http://a.m.o/')
        self.check_status('success', target_url='http://a.m.o/')

    def test_error(self):
        self.github.error('http://a.m.o/')
        self.check_status(
            'error', description=mock.ANY, target_url='http://a.m.o/'
        )

    def test_failure(self):
        self.github.failure()
        self.check_status('failure', description=mock.ANY)

    def test_get(self):
        self.github.get()
        self.requests.get.assert_called_with('https://github/zip')


class TestRezip(AMOPaths, TestCase):
    def setUp(self):
        self.response = mock.Mock()
        self.response.content = open(self.xpi_path('github-repo')).read()

    def test_rezip(self):
        new_path = rezip_file(self.response, 1)
        with open(new_path, 'r') as new_file:
            new_zip = zipfile.ZipFile(new_file)
            self.assertSetEqual(
                set([f.filename for f in new_zip.filelist]),
                set(['manifest.json', 'index.js']),
            )

    def test_badzip(self):
        with self.settings(FILE_UNZIP_SIZE_LIMIT=5):
            with self.assertRaises(forms.ValidationError):
                rezip_file(self.response, 1)
