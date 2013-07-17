import base64
import json
from nose import SkipTest
from nose.tools import eq_

from mock import patch

import amo.tests
from addons.models import Addon, AddonUser
from files.models import FileUpload
from users.models import UserProfile

from mkt.api.tests.test_oauth import BaseOAuth
from mkt.api.tests.test_handlers import CreateHandler
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class ValidationHandler(BaseOAuth):
    fixtures = fixture('user_2519', 'user_admin')

    def setUp(self):
        super(ValidationHandler, self).setUp()
        self.list_url = ('api_dispatch_list', {'resource_name': 'validation'})
        self.get_url = None
        self.user = UserProfile.objects.get(pk=2519)

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.list_url), 'post')

    def create(self):
        res = self.client.post(self.list_url,
                               data=json.dumps({'manifest':
                                                'http://foo.com'}))
        self.get_url = ('api_dispatch_detail',
                        {'resource_name': 'validation',
                         'pk': json.loads(res.content)['id']})
        return res

    def get(self):
        return FileUpload.objects.all()[0]

    def get_error(self, response):
        return json.loads(response.content)['error_message']


class TestAddValidationHandler(ValidationHandler):

    def test_verbs(self):
        self._allowed_verbs(self.list_url, ['post'])

    def test_good(self):
        res = self.create()
        eq_(res.status_code, 201)  # Note! This should be a 202.
        content = json.loads(res.content)
        eq_(content['processed'], True)
        obj = FileUpload.objects.get(uuid=content['id'])
        eq_(obj.user, self.user)

    @patch('mkt.api.resources.tasks.fetch_manifest')
    def test_fetch(self, fetch):
        self.create()
        assert fetch.called

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
        res = self.anon.post(self.list_url,
                             data=json.dumps({'manifest':
                                              'http://foo.com'}))
        eq_(res.status_code, 201)


class TestPackagedValidation(amo.tests.AMOPaths, ValidationHandler):

    def setUp(self):
        super(TestPackagedValidation, self).setUp()
        name = 'mozball.zip'
        path = self.packaged_app_path(name)
        self.file = base64.b64encode(open(path).read())
        self.data = {'data': self.file, 'name': name,
                     'type': 'application/zip'}

    def create(self):
        res = self.client.post(self.list_url,
                               data=json.dumps({'upload': self.data}))
        if res.status_code < 400:
            self.get_url = ('api_dispatch_detail',
                            {'resource_name': 'validation',
                             'pk': json.loads(res.content)['id']})

        return res

    def test_good(self):
        raise SkipTest('Caused zipfile IOErrors')
        res = self.create()
        eq_(res.status_code, 201)  # Note! This should be a 202.
        content = json.loads(res.content)
        eq_(content['processed'], True)
        obj = FileUpload.objects.get(uuid=content['id'])
        eq_(obj.user, self.user)

    @patch('mkt.constants.MAX_PACKAGED_APP_SIZE', 2)
    def test_too_big(self):
        res = self.create()
        eq_(res.status_code, 413)
        eq_(json.loads(res.content)['reason'],
            'Packaged app too large for submission by this method. '
            'Packages must be smaller than 2 bytes.')

    def form_errors(self, data, errors):
        self.data = data
        res = self.create()
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
        self.get_url = ('api_dispatch_detail',
                        {'resource_name': 'validation', 'pk': res.pk})
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
        url = ('api_dispatch_detail',
                {'resource_name': 'validation', 'pk': '123123123'})
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


class TestAppStatusHandler(CreateHandler, amo.tests.AMOPaths):
    fixtures = fixture('user_2519', 'platform_all')

    def setUp(self):
        super(TestAppStatusHandler, self).setUp()
        self.list_url = ('api_dispatch_list', {'resource_name': 'status'})

    def create_app(self):
        obj = self.create()
        res = self.client.post(('api_dispatch_list', {'resource_name': 'app'}),
                               data=json.dumps({'manifest': obj.uuid}))
        pk = json.loads(res.content)['id']
        self.get_url = ('api_dispatch_detail',
                        {'resource_name': 'status', 'pk': pk})
        return Webapp.objects.get(pk=pk)

    def test_verbs(self):
        self._allowed_verbs(self.list_url, [])

    def test_has_no_cors(self):
        res = self.client.get(self.list_url)
        assert 'access-control-allow-origin' not in res

    def test_status(self):
        self.create_app()
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['disabled_by_user'], False)
        eq_(data['status'], 'incomplete')

    def test_disable(self):
        app = self.create_app()
        res = self.client.patch(self.get_url,
                                data=json.dumps({'disabled_by_user': True}))
        eq_(res.status_code, 202, res.content)
        app = app.__class__.objects.get(pk=app.pk)
        eq_(app.disabled_by_user, True)
        eq_(app.status, amo.STATUS_NULL)

    def test_change_status_fails(self):
        self.create_app()
        res = self.client.patch(self.get_url,
                        data=json.dumps({'status': 'pending'}))
        eq_(res.status_code, 400)
        assert isinstance(self.get_error(res)['status'], list)

    @patch('mkt.webapps.models.Webapp.is_complete')
    def test_change_status_passes(self, is_complete):
        is_complete.return_value = True, []
        app = self.create_app()
        res = self.client.patch(self.get_url,
                        data=json.dumps({'status': 'pending'}))
        eq_(res.status_code, 202, res.content)
        eq_(app.__class__.objects.get(pk=app.pk).status, amo.STATUS_PENDING)

    @patch('mkt.webapps.models.Webapp.is_complete')
    def test_cant_skip(self, is_complete):
        is_complete.return_value = True, []
        app = self.create_app()
        res = self.client.patch(self.get_url,
                        data=json.dumps({'status': 'public'}))
        eq_(res.status_code, 400)
        assert 'available choices' in self.get_error(res)['status'][0]
        eq_(Addon.objects.get(pk=app.pk).status, amo.STATUS_NULL)

    def test_public_waiting(self):
        app = self.create_app()
        app.update(status=amo.STATUS_PUBLIC_WAITING)
        res = self.client.patch(self.get_url,
                        data=json.dumps({'status': 'public'}))
        eq_(res.status_code, 202)
        eq_(app.__class__.objects.get(pk=app.pk).status, amo.STATUS_PUBLIC)


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
