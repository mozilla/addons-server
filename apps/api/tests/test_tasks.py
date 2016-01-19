import json

import mock
from django.test.utils import override_settings

from apps.amo.tests import AMOPaths
from apps.api.tasks import process_results, process_webhook
from apps.files.models import FileUpload
from apps.api.tests.test_github import GithubBase


@override_settings(GITHUB_API_USER='key', GITHUB_API_TOKEN='token')
class TestGithub(AMOPaths, GithubBase):

    def test_good_results(self):
        upload = FileUpload.objects.create(
            validation=json.dumps({'errors': []})
        )
        process_results(upload.pk, self.data)
        self.check_status('success')

    def test_failed_results(self):
        upload = FileUpload.objects.create()
        process_results(upload.pk, self.data)
        self.check_status('failure', description=mock.ANY)

    def test_error_results(self):
        upload = FileUpload.objects.create(
            validation=json.dumps({
                'errors': [{
                    'description': 'foo',
                    'file': 'some/file',
                    'line': 3,
                }]
            })
        )
        process_results(upload.pk, self.data)
        comment, error = self.requests.post.call_args_list
        self.check_status(
            'comment',
            call=comment, url=self.data['comment_url'],
            position=3, body='foo', path='some/file', commit_id='some:sha')
        self.check_status('error', call=error, description=mock.ANY)

    def test_webhook(self):
        upload = FileUpload.objects.create()

        self.response = mock.Mock()
        self.response.content = open(self.xpi_path('github-repo')).read()
        self.requests.get.return_value = self.response

        process_webhook(upload.pk, self.data)
        self.check_status('success')
