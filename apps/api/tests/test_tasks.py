import json

import mock
from django.test.utils import override_settings

from apps.amo.helpers import absolutify
from apps.amo.tests import AMOPaths
from apps.api.tasks import filter_messages, process_results, process_webhook
from apps.amo.urlresolvers import reverse
from apps.files.models import FileUpload
from apps.api.tests.test_github import GithubBase


@override_settings(GITHUB_API_USER='key', GITHUB_API_TOKEN='token')
class TestGithub(AMOPaths, GithubBase):

    def get_url(self, upload_pk):
        return absolutify(
            reverse('devhub.standalone_upload_detail', args=[upload_pk]))

    def test_good_results(self):
        upload = FileUpload.objects.create(
            validation=json.dumps({'success': True, 'errors': 0})
        )
        process_results(upload.pk, self.data)
        self.check_status('success', target_url=self.get_url(upload.pk))

    def test_failed_results(self):
        upload = FileUpload.objects.create()
        process_results(upload.pk, self.data)
        self.check_status('failure', description=mock.ANY)

    def test_no_line(self):
        upload = FileUpload.objects.create(
            validation=json.dumps({
                'errors': 1,
                'messages': [{
                    'description': ['foo'],
                    'file': 'some/file',
                    # The validator will return this for some errors.
                    'line': None,
                    'type': 'error'
                }]
            })
        )
        process_results(upload.pk, self.data)
        comment, error = self.requests.post.call_args_list

        self.check_status(
            'comment',
            call=comment, url=self.data['comment_url'],
            position=1, body='foo', path='some/file', commit_id='some:sha')

    def test_error_results(self):
        upload = FileUpload.objects.create(
            validation=json.dumps({
                'errors': 1,
                'messages': [{
                    'description': ['foo'],
                    'file': 'some/file',
                    'line': 3,
                    'type': 'error'
                }]
            })
        )
        process_results(upload.pk, self.data)
        comment, error = self.requests.post.call_args_list

        self.check_status(
            'comment',
            call=comment, url=self.data['comment_url'],
            position=3, body='foo', path='some/file', commit_id='some:sha')

        self.check_status(
            'error',
            call=error, description=mock.ANY,
            target_url=self.get_url(upload.pk))

    def test_webhook(self):
        upload = FileUpload.objects.create()

        self.response = mock.Mock()
        self.response.content = open(self.xpi_path('github-repo')).read()
        self.requests.get.return_value = self.response

        process_webhook(upload.pk, self.data)
        self.check_status('success', target_url=self.get_url(upload.pk))


class TestGithubFilter(GithubBase):

    def test_over_limit(self):
        with self.settings(GITHUB_COMMENTS_PER_VALIDATION=1):
            messages = [{'id': 1, 'type': 'error'}, {'id': 2, 'type': 'error'}]
            assert filter_messages(messages) == [{'id': 1, 'type': 'error'}]

    def test_wrong_type(self):
        with self.settings(GITHUB_COMMENT_TYPES=['error']):
            messages = [
                {'id': 1, 'type': 'warning'}, {'id': 2, 'type': 'error'}]
            assert filter_messages(messages) == [{'id': 2, 'type': 'error'}]

    def test_multiple_types(self):
        with self.settings(GITHUB_COMMENT_TYPES=['error', 'warning']):
            messages = [
                {'id': 1, 'type': 'warning'}, {'id': 2, 'type': 'error'}]
            assert len(filter_messages(messages)) == 2
