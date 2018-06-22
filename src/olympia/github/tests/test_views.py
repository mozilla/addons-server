import json

from django.utils.http import urlencode

import mock
import requests

from olympia.amo.tests import AMOPaths, TestCase, reverse_ns
from olympia.files.models import FileUpload
from olympia.github.tests.test_github import (
    GithubBaseTestCase, example_pull_request)


class TestGithubView(AMOPaths, GithubBaseTestCase, TestCase):

    def setUp(self):
        super(TestGithubView, self).setUp()
        self.url = reverse_ns('github.validate')

    def post(self, data, header=None, data_type=None):
        data_type = data_type or 'application/json'
        if (data_type == 'application/json'):
            data = json.dumps(data)
        elif (data_type == 'application/x-www-form-urlencoded'):
            data = urlencode({'payload': json.dumps(data)})
        return self.client.post(
            self.url, data=data,
            content_type=data_type,
            HTTP_X_GITHUB_EVENT=header or 'pull_request'
        )

    def complete(self):
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

    def test_good_not_json(self):
        self.setup_xpi()
        assert self.post(
            example_pull_request,
            data_type='application/x-www-form-urlencoded').status_code == 201
        self.complete()

    def test_good(self):
        self.setup_xpi()
        assert self.post(example_pull_request).status_code == 201
        self.complete()
