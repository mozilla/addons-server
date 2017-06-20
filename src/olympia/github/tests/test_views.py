import json
import mock
import requests

from olympia.amo.tests import AMOPaths, TestCase
from olympia.files.models import FileUpload
from olympia.amo.urlresolvers import reverse

from olympia.github.tests.test_github import (
    example_pull_request, GithubBaseTestCase)


class TestGithubView(AMOPaths, GithubBaseTestCase, TestCase):

    def setUp(self):
        super(TestGithubView, self).setUp()
        self.url = reverse('github.validate')

    def post(self, data, header=None):
        return self.client.post(
            self.url, data=json.dumps(data),
            content_type='application/json',
            HTTP_X_GITHUB_EVENT=header or 'pull_request'
        )

    def test_not_pull_request(self):
        assert self.post({}, header='meh').status_code == 200

    def test_bad_pull_request(self):
        assert self.post({'pull_request': {}}).status_code == 422

    def setup_xpi(self):
        self.response = mock.Mock()
        self.response.content = open(self.xpi_path('github-repo')).read()
        self.requests.get.return_value = self.response

    def test_pending_fails(self):
        self.setup_xpi()

        post = mock.Mock()
        # GitHub returns a 404 when the addons-robot account does not
        # have write access.
        post.status_code = 404
        post.raise_for_status.side_effect = requests.HTTPError(response=post)
        self.requests.post.return_value = post

        res = self.post(example_pull_request)
        assert 'write access' in json.loads(res.content)['details']

    def test_good(self):
        self.setup_xpi()

        self.post(example_pull_request)
        pending, success = self.requests.post.call_args_list
        self.check_status(
            'pending',
            call=pending,
            url='https://api.github.com/repos/org/repo/statuses/abc'
        )
        self.check_status(
            'success',
            call=success,
            url='https://api.github.com/repos/org/repo/statuses/abc',
            target_url=mock.ANY
        )

        assert FileUpload.objects.get()
