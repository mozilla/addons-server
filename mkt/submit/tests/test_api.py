import base64
import json

from nose.tools import eq_, ok_
from mock import patch

from django.core.urlresolvers import reverse

import amo.tests
from addons.models import AddonUser
from files.models import FileUpload
from users.models import UserProfile

from mkt.api.tests.test_oauth import BaseOAuth, RestOAuth
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


def fake_fetch_manifest(url, upload_pk=None, **kw):
    upload = FileUpload.objects.get(pk=upload_pk)
    upload.update(validation=json.dumps({'fake_validation': True}))


class ValidationHandler(RestOAuth):
    fixtures = fixture('user_2519', 'user_admin')

    def setUp(self):
        super(ValidationHandler, self).setUp()
        self.list_url = reverse('app-validation-list')
        self.get_url = None
        self.user = UserProfile.objects.get(pk=2519)

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.list_url), 'post', 'get')

    @patch('mkt.submit.api.tasks')
    def create(self, tasks_mock, client=None):
        tasks_mock.fetch_manifest.side_effect = fake_fetch_manifest
        manifest_url = u'http://foo.com/'

        if client is None:
            client = self.client

        res = client.post(self.list_url,
                          data=json.dumps({'manifest': manifest_url}))
        data = json.loads(res.content)
        self.get_url = reverse('app-validation-detail',
            kwargs={'pk': data['id']})
        eq_(tasks_mock.fetch_manifest.call_args[0][0], manifest_url)
        eq_(tasks_mock.fetch_manifest.call_args[0][1], data['id'])
        return res, data

    def get(self):
        return FileUpload.objects.all()[0]

    def get_error(self, response):
        return json.loads(response.content)


class TestAddValidationHandler(ValidationHandler):

    def test_verbs(self):
        self._allowed_verbs(self.list_url, ['post'])

    def test_good(self):
        res, data = self.create()
        eq_(res.status_code, 201)
        eq_(data['processed'], True)
        obj = FileUpload.objects.get(uuid=data['id'])
        eq_(obj.user, self.user)

    def test_missing(self):
        res = self.client.post(self.list_url, data=json.dumps({}))
        eq_(res.status_code, 400)
        eq_(self.get_error(res)['manifest'], ['This field is required.'])

    def test_bad(self):
        res = self.client.post(self.list_url,
                               data=json.dumps({'manifest': 'blurgh'}))
        eq_(res.status_code, 400)
        eq_(self.get_error(res)['manifest'], ['Enter a valid URL.'])

    def test_anon(self):
        res, data = self.create(client=self.anon)
        eq_(res.status_code, 201)
        eq_(data['processed'], True)
        obj = FileUpload.objects.get(uuid=data['id'])
        eq_(obj.user, None)


class TestPackagedValidation(amo.tests.AMOPaths, ValidationHandler):

    def setUp(self):
        super(TestPackagedValidation, self).setUp()
        name = 'mozball.zip'
        path = self.packaged_app_path(name)
        self.file = base64.b64encode(open(path).read())
        self.data = {'data': self.file, 'name': name,
                     'type': 'application/zip'}

    @patch('mkt.submit.api.tasks')
    def create(self, tasks_mock, client=None):
        if client is None:
            client = self.client

        res = client.post(self.list_url,
                          data=json.dumps({'upload': self.data}))
        data = json.loads(res.content)
        self.get_url = reverse('app-validation-detail',
            kwargs={'pk': data['id']})
        eq_(tasks_mock.validator.delay.call_args[0][0], data['id'])
        return res

    def test_good(self):
        res = self.create()
        eq_(res.status_code, 202)
        content = json.loads(res.content)
        eq_(content['processed'], False)
        obj = FileUpload.objects.get(uuid=content['id'])
        eq_(obj.user, self.user)

    @patch('mkt.developers.forms.MAX_PACKAGED_APP_SIZE', 2)
    def test_too_big(self):
        res = self.client.post(self.list_url,
                               data=json.dumps({'upload': self.data}))
        eq_(res.status_code, 400)
        eq_(json.loads(res.content)['upload'][0],
            'Packaged app too large for submission. '
            'Packages must be smaller than 2 bytes.')

    def form_errors(self, data, errors):
        res = self.client.post(self.list_url,
                               data=json.dumps({'upload': data}))
        eq_(res.status_code, 400)
        eq_(self.get_error(res)['upload'], errors)

    def test_missing(self):
        self.form_errors({'data': self.file, 'name': 'mozball.zip'},
                         [u'Type and data are required.'])

    def test_missing_name(self):
        self.form_errors({'data': self.file, 'type': 'application/zip'},
                         [u'Name not specified.'])

    def test_wrong(self):
        self.form_errors({'data': self.file, 'name': 'mozball.zip',
                          'type': 'application/foo'},
                         [u'Type must be application/zip.'])

    def test_invalid(self):
        self.form_errors({'data': 'x', 'name': 'mozball.zip',
                          'type': 'application/foo'},
                         [u'File must be base64 encoded.'])


class TestGetValidationHandler(ValidationHandler):

    def create(self):
        res = FileUpload.objects.create(user=self.user, path='http://foo.com')
        self.get_url = reverse('app-validation-detail', kwargs={'pk': res.pk})
        return res

    def test_verbs(self):
        self.create()
        self._allowed_verbs(self.get_url, ['get'])

    def test_check(self):
        self.create()
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)

    def test_anon(self):
        self.create()
        res = self.anon.get(self.get_url)
        eq_(res.status_code, 200)

    def test_not_found(self):
        url = reverse('app-validation-detail', kwargs={'pk': 12121212121212})
        res = self.client.get(url)
        eq_(res.status_code, 404)

    def test_not_run(self):
        self.create()
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['processed'], False)

    def test_pass(self):
        obj = self.create()
        obj.update(valid=True)
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['processed'], True)
        eq_(data['valid'], True)

    def test_failure(self):
        obj = self.create()
        error = '{"errors": 1, "messages": [{"tier": 1, "message": "nope"}]}'
        obj.update(valid=False, validation=error)
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['processed'], True)
        eq_(data['valid'], False)


class TestAppStatusHandler(RestOAuth, amo.tests.AMOPaths):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestAppStatusHandler, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        AddonUser.objects.create(addon=self.app, user=self.user.get_profile())
        self.get_url = reverse('app-status-detail', kwargs={'pk': self.app.pk})

    def get(self, expected_status=200):
        res = self.client.get(self.get_url)
        eq_(res.status_code, expected_status)
        data = json.loads(res.content)
        return res, data

    def test_verbs(self):
        self._allowed_verbs(self.get_url, ['get', 'patch'])  # FIXME disallow put

    def test_has_no_cors(self):
        res = self.client.get(self.get_url)
        assert 'access-control-allow-origin' not in res

    def test_status(self):
        res, data = self.get()
        eq_(self.app.status, amo.STATUS_PUBLIC)
        eq_(data['status'], 'public')
        eq_(data['disabled_by_user'], False)

        self.app.update(status=amo.STATUS_NULL)
        res, data = self.get()
        eq_(data['status'], 'incomplete')
        eq_(data['disabled_by_user'], False)

        self.app.update(status=amo.STATUS_PENDING)
        res, data = self.get()
        eq_(data['status'], 'pending')
        eq_(data['disabled_by_user'], False)

        self.app.update(disabled_by_user=True)
        res, data = self.get()
        eq_(data['status'], 'pending')
        eq_(data['disabled_by_user'], True)

    def test_status_not_mine(self):
        AddonUser.objects.get(user=self.user.get_profile()).delete()
        res = self.client.get(self.get_url)
        eq_(res.status_code, 403)

    def test_disable(self):
        eq_(self.app.disabled_by_user, False)
        res = self.client.patch(self.get_url,
                                data=json.dumps({'disabled_by_user': True}))
        eq_(res.status_code, 200)
        self.app.reload()
        eq_(self.app.disabled_by_user, True)
        eq_(self.app.status, amo.STATUS_PUBLIC)  # Unchanged, doesn't matter.

    def test_disable_not_mine(self):
        AddonUser.objects.get(user=self.user.get_profile()).delete()
        res = self.client.patch(self.get_url,
                                data=json.dumps({'disabled_by_user': True}))
        eq_(res.status_code, 403)

    def test_change_status_to_pending_fails(self):
        res = self.client.patch(self.get_url,
                                data=json.dumps({'status': 'pending'}))
        eq_(res.status_code, 400)
        data = json.loads(res.content)
        ok_('status' in data)

    @patch('mkt.webapps.models.Webapp.is_fully_complete')
    def test_change_status_to_pending(self, is_fully_complete):
        is_fully_complete.return_value = True, []
        self.app.update(status=amo.STATUS_NULL)
        res = self.client.patch(self.get_url,
                                data=json.dumps({'status': 'pending'}))
        eq_(res.status_code, 200)
        self.app.reload()
        eq_(self.app.disabled_by_user, False)
        eq_(self.app.status, amo.STATUS_PENDING)

    def test_change_status_to_public_fails(self):
        self.app.update(status=amo.STATUS_PENDING)
        res = self.client.patch(self.get_url,
                                data=json.dumps({'status': 'public'}))
        eq_(res.status_code, 400)
        data = json.loads(res.content)
        ok_('status' in data)
        eq_(self.app.reload().status, amo.STATUS_PENDING)

    @patch('mkt.webapps.models.Webapp.is_fully_complete')
    def test_incomplete_app(self, is_fully_complete):
        is_fully_complete.return_value = False, ['Stop !', 'Hammer Time !']
        self.app.update(status=amo.STATUS_NULL)
        res = self.client.patch(self.get_url,
                                data=json.dumps({'status': 'pending'}))
        eq_(res.status_code, 400)
        data = json.loads(res.content)
        eq_(data['status'][0], 'Stop !')
        eq_(data['status'][1], 'Hammer Time !')

    @patch('mkt.webapps.models.Webapp.is_fully_complete')
    def test_public_waiting(self, is_fully_complete):
        is_fully_complete.return_value = True, []
        self.app.update(status=amo.STATUS_PUBLIC_WAITING)
        res = self.client.patch(self.get_url,
                        data=json.dumps({'status': 'public'}))
        eq_(res.status_code, 200)
        eq_(self.app.reload().status, amo.STATUS_PUBLIC)


class TestPreviewHandler(BaseOAuth, amo.tests.AMOPaths):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestPreviewHandler, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=2519)
        AddonUser.objects.create(user=self.user, addon=self.app)
        self.file = base64.b64encode(open(self.preview_image(), 'r').read())
        self.list_url = ('api_dispatch_list', {'resource_name': 'preview'},
                         {'app': self.app.pk})
        self.good = {'file': {'data': self.file, 'type': 'image/jpg'},
                     'position': 1}

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.list_url), 'post')

    def test_no_addon(self):
        _list_url = ('api_dispatch_list', {'resource_name': 'preview'})
        res = self.client.post(_list_url, data=json.dumps(self.good))
        eq_(res.status_code, 404)

    def test_post_preview(self):
        res = self.client.post(self.list_url, data=json.dumps(self.good))
        eq_(res.status_code, 201)
        previews = self.app.previews
        eq_(previews.count(), 1)
        eq_(previews.all()[0].position, 1)

    def test_wrong_url(self):
        url = list(self.list_url)
        url[-1]['app'] = 'booyah'
        res = self.client.post(url, data=json.dumps(self.good))
        eq_(res.status_code, 400)
        eq_(self.get_error(res)['app'], [u'Enter a whole number.'])

    def test_not_mine(self):
        self.app.authors.clear()
        res = self.client.post(self.list_url, data=json.dumps(self.good))
        eq_(res.status_code, 403)

    def test_position_missing(self):
        data = {'file': {'data': self.file, 'type': 'image/jpg'}}
        res = self.client.post(self.list_url, data=json.dumps(data))
        eq_(res.status_code, 400)
        eq_(self.get_error(res)['position'], ['This field is required.'])

    def test_preview_missing(self):
        res = self.client.post(self.list_url, data=json.dumps({}))
        eq_(res.status_code, 400)
        eq_(self.get_error(res)['position'], ['This field is required.'])

    def create(self):
        self.client.post(self.list_url, data=json.dumps(self.good))
        self.preview = self.app.previews.all()[0]
        self.get_url = ('api_dispatch_detail',
                        {'resource_name': 'preview', 'pk': self.preview.pk})

    def test_delete(self):
        self.create()
        res = self.client.delete(self.get_url)
        eq_(res.status_code, 204)
        eq_(self.app.previews.count(), 0)

    def test_delete_not_mine(self):
        self.create()
        self.app.authors.clear()
        res = self.client.delete(self.get_url)
        eq_(res.status_code, 403)

    def test_delete_not_there(self):
        self.get_url = ('api_dispatch_detail',
                        {'resource_name': 'preview', 'pk': 123})
        res = self.client.delete(self.get_url)
        eq_(res.status_code, 404)

    def test_get(self):
        self.create()
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)

    def test_get_not_mine(self):
        self.create()
        self.app.authors.clear()
        res = self.client.get(self.get_url)
        eq_(res.status_code, 403)

    def test_get_not_there(self):
        self.get_url = ('api_dispatch_detail',
                        {'resource_name': 'preview', 'pk': 123})
        res = self.client.get(self.get_url)
        eq_(res.status_code, 404)
