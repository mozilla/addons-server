import json

from django.test.utils import override_settings

import mock

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import AMOPaths
from olympia.amo.urlresolvers import reverse
from olympia.files.models import FileUpload
from olympia.github.tasks import process_results, process_webhook
from olympia.github.tests.test_github import GithubBaseTestCase


@override_settings(GITHUB_API_USER='key', GITHUB_API_TOKEN='token')
class TestGithub(AMOPaths, GithubBaseTestCase):
    def get_url(self, upload_uuid):
        return absolutify(reverse('devhub.upload_detail', args=[upload_uuid]))

    def test_good_results(self):
        upload = FileUpload.objects.create(
            validation=json.dumps({'success': True, 'errors': 0})
        )
        process_results(upload.pk, self.data)
        self.check_status('success', target_url=self.get_url(upload.uuid))

    def test_failed_results(self):
        upload = FileUpload.objects.create()
        process_results(upload.pk, self.data)
        self.check_status('failure', description=mock.ANY)

    def test_error_results(self):
        upload = FileUpload.objects.create(
            validation=json.dumps(
                {
                    'errors': 1,
                    'messages': [
                        {
                            'description': ['foo'],
                            'file': 'some/file',
                            'line': 3,
                            'type': 'error',
                        }
                    ],
                }
            )
        )
        process_results(upload.pk, self.data)
        error = self.requests.post.call_args_list[0]
        self.check_status(
            'error',
            call=error,
            description=mock.ANY,
            target_url=self.get_url(upload.uuid),
        )

    def test_webhook(self):
        upload = FileUpload.objects.create()

        self.response = mock.Mock()
        self.response.content = open(self.xpi_path('github-repo')).read()
        self.requests.get.return_value = self.response

        process_webhook(upload.pk, self.data)
        self.check_status('success', target_url=self.get_url(upload.uuid))
