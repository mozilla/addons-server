import json

from mock import patch
from nose.tools import eq_

from files.models import FileUpload
from mkt.api.tests.test_oauth import BaseOAuth
from users.models import UserProfile


class ValidationHandler(BaseOAuth):
    fixtures = ['base/user_2519', 'base/users']

    def setUp(self):
        super(ValidationHandler, self).setUp()
        self.url = 'api.validation'
        self.consumer = self.accepted_consumer
        self.user = UserProfile.objects.get(pk=2519)

    def create(self):
        return self.client.post(self.url, consumer=self.consumer,
                                data={'manifest': 'http://foo.com'})

    def get(self):
        return FileUpload.objects.all()[0]

    def get_error(self, response):
        return json.loads(response.content)['error']


class TestAddValidationHandler(ValidationHandler):

    def test_good(self):
        res = self.create()
        eq_(res.status_code, 202)
        uuid = json.loads(res.content)['id']
        eq_(FileUpload.objects.filter(uuid=uuid).count(), 1)

    @patch('mkt.api.handlers.tasks.fetch_manifest.delay')
    def test_fetch(self, fetch):
        self.create()
        assert fetch.called

    def test_missing(self):
        res = self.client.post(self.url, consumer=self.consumer, data={})
        eq_(res.status_code, 400)
        eq_(self.get_error(res)['manifest'], ['This field is required.'])

    def test_bad(self):
        res = self.client.post(self.url, consumer=self.consumer,
                               data={'manifest': 'blurgh'})
        eq_(res.status_code, 400)
        eq_(self.get_error(res)['manifest'], ['Enter a valid URL.'])


class TestGetValidationHandler(ValidationHandler):

    def create(self):
        return FileUpload.objects.create(user=self.user,
                                         path='http://foo.com')

    def test_check(self):
        obj = self.create()
        res = self.client.get((self.url, obj.pk), consumer=self.consumer)
        eq_(res.status_code, 200)

    def test_not_owner(self):
        obj = self.create()
        obj.update(user=UserProfile.objects.get(email='admin@mozilla.com'))
        res = self.client.get((self.url, obj.pk), consumer=self.consumer)
        eq_(res.status_code, 401)
        eq_(self.get_error(res), 'Forbidden')

    def test_not_found(self):
        res = self.client.get((self.url, 'abc'), consumer=self.consumer)
        eq_(res.status_code, 404)
        eq_(self.get_error(res), 'Not Found')

    def test_not_run(self):
        obj = self.create()
        res = self.client.get((self.url, obj.pk), consumer=self.consumer)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['processed'], False)

    def test_pass(self):
        obj = self.create()
        obj.update(valid=True)
        res = self.client.get((self.url, obj.pk), consumer=self.consumer)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['processed'], True)
        eq_(data['valid'], True)

    def test_failure(self):
        obj = self.create()
        error = '{"errors": 1, "messages": [{"tier": 1, "message": "nope"}]}'
        obj.update(valid=False, validation=error)
        res = self.client.get((self.url, obj.pk), consumer=self.consumer)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['processed'], True)
        eq_(data['valid'], False)
        eq_(data['validation'], json.loads(error))
