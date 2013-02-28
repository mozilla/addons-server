import codecs
from contextlib import contextmanager
from cStringIO import StringIO
import json
import os
import shutil
import socket
import tempfile
import urllib2

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage

import mock
from nose.tools import eq_
from PIL import Image

import amo
import amo.tests
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from amo.utils import ImageCheck
from files.models import FileUpload

import mkt
from mkt.constants import APP_IMAGE_SIZES
from mkt.developers import tasks
from mkt.submit.tests.test_views import BaseWebAppTest
from mkt.webapps.models import AddonExcludedRegion as AER, ImageAsset, Webapp


def test_resize_icon_shrink():
    """ Image should be shrunk so that the longest side is 32px. """

    resize_size = 32
    final_size = (32, 12)

    _uploader(resize_size, final_size)


def test_resize_icon_enlarge():
    """ Image stays the same, since the new size is bigger than both sides. """

    resize_size = 1000
    final_size = (339, 128)

    _uploader(resize_size, final_size)


def test_resize_icon_same():
    """ Image stays the same, since the new size is the same. """

    resize_size = 339
    final_size = (339, 128)

    _uploader(resize_size, final_size)


def test_resize_icon_list():
    """ Resize multiple images at once. """

    resize_size = [32, 82, 100]
    final_size = [(32, 12), (82, 30), (100, 37)]

    _uploader(resize_size, final_size)


def _uploader(resize_size, final_size):
    img = get_image_path('mozilla.png')
    original_size = (339, 128)

    src = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png",
                                      delete=False)

    # resize_icon removes the original
    shutil.copyfile(img, src.name)

    with storage.open(src.name) as fp:
        src_image = Image.open(fp)
        src_image.load()
    eq_(src_image.size, original_size)

    if isinstance(final_size, list):
        for rsize, fsize in zip(resize_size, final_size):
            dest_name = os.path.join(settings.ADDON_ICONS_PATH, '1234')

            tasks.resize_icon(src.name, dest_name, resize_size, locally=True)
            with storage.open("%s-%s.png" % (dest_name, rsize)) as fp:
                dest_image = Image.open(fp)
                dest_image.load()

            # Assert that the width is always identical.
            eq_(dest_image.size[0], fsize[0])
            # Assert that the height can be a wee bit fuzzy.
            assert -1 <= dest_image.size[1] - fsize[1] <= 1, (
                "Got width %d, expected %d" %
                    (fsize[1], dest_image.size[1]))

            if os.path.exists(dest_image.filename):
                os.remove(dest_image.filename)
            assert not os.path.exists(dest_image.filename)
    else:
        dest = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png")
        tasks.resize_icon(src.name, dest.name, resize_size, locally=True)
        with storage.open(dest.name) as fp:
            dest_image = Image.open(fp)
            dest_image.load()

        # Assert that the width is always identical.
        eq_(dest_image.size[0], final_size[0])
        # Assert that the height can be a wee bit fuzzy.
        assert -1 <= dest_image.size[1] - final_size[1] <= 1, (
            "Got width %d, expected %d" % (final_size[1], dest_image.size[1]))

    assert not os.path.exists(src.name)


@mock.patch('mkt.developers.tasks.get_hue', lambda img: 123)
@mock.patch('mkt.developers.tasks.ImageAsset')
def test_resize_image_asset(ia):
    _instance = mock.Mock()
    ia.objects.get.return_value = _instance


    img = get_image_path('mozilla.png')
    original_size = (339, 128)

    with storage.open(img) as fp:
        src_image = Image.open(fp)
        eq_(src_image.size, original_size)

    dest = tempfile.NamedTemporaryFile(mode='r+w+b', suffix='.png')
    # Make it resize to some arbitrary size that's larger on both sides than
    # the source image. This is where the behavior differs from resize_image.
    tasks.resize_imageasset(img, dest.name, (500, 500), instance='foo',
                            locally=True)
    with storage.open(dest.name) as fp:
        dest_image = Image.open(fp)
        eq_(dest_image.size, (500, 500))

    # Assert that the asset's instance gets updated with the new hue.
    ia.objects.get.assert_called_with(pk='foo')
    _instance.update.assert_called_with(hue=123)


class TestValidator(amo.tests.TestCase):

    def setUp(self):
        self.upload = FileUpload.objects.create()
        assert not self.upload.valid

    def get_upload(self):
        return FileUpload.objects.get(pk=self.upload.pk)

    @mock.patch('mkt.developers.tasks.run_validator')
    def test_pass_validation(self, _mock):
        _mock.return_value = '{"errors": 0}'
        tasks.validator(self.upload.pk)
        assert self.get_upload().valid

    @mock.patch('mkt.developers.tasks.run_validator')
    def test_fail_validation(self, _mock):
        _mock.return_value = '{"errors": 2}'
        tasks.validator(self.upload.pk)
        assert not self.get_upload().valid

    @mock.patch('mkt.developers.tasks.run_validator')
    def test_validation_error(self, _mock):
        _mock.side_effect = Exception
        eq_(self.upload.task_error, None)
        with self.assertRaises(Exception):
            tasks.validator(self.upload.pk)
        error = self.get_upload().task_error
        assert error is not None
        assert error.startswith('Traceback (most recent call last)'), error

    @mock.patch('mkt.developers.tasks.validate_app')
    @mock.patch('mkt.developers.tasks.storage.open')
    def test_validate_manifest(self, _open, _mock):
        self.get_upload().update(is_webapp=True)
        _open.return_value = StringIO('')
        _mock.return_value = '{"errors": 0}'
        tasks.validator(self.upload.pk)
        assert _mock.called

    @mock.patch('mkt.developers.tasks.validate_packaged_app')
    @mock.patch('zipfile.is_zipfile')
    def test_validate_packaged_app(self, _zipfile, _mock):
        self.get_upload().update(is_webapp=True)
        _zipfile.return_value = True
        _mock.return_value = '{"errors": 0}'
        tasks.validator(self.upload.pk)
        assert _mock.called


storage_open = storage.open
def _mock_hide_64px_icon(path, *args, **kwargs):
    """
    A function that mocks `storage.open` and throws an IOError if you try to
    open a 128x128px icon.
    """
    if '128' in path:
        raise IOError('No 128px icon for you!')
    return storage_open(path, *args, **kwargs)


class TestGenerateImageAssets(amo.tests.TestCase):
    """Test that image assets get generated properly."""
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.app = Webapp.objects.get(id=337141)
        self.app.get_icon_dir = lambda: os.path.join(
            os.path.dirname(__file__), 'icons/')

    def test_generated_image_assets(self):
        tasks.generate_image_assets(self.app)
        for asset in APP_IMAGE_SIZES:
            ia = ImageAsset.objects.get(addon=self.app,
                                        slug=asset['slug'])
            with storage.open(ia.image_path) as fp:
                im = Image.open(fp)
                im.load()
            eq_(im.size, asset['size'])

    def test_generated_image_assets_slug(self):
        # We're going to generate assets for only one type.
        asset = APP_IMAGE_SIZES[0]
        slug = asset['slug']

        tasks.generate_image_assets(self.app, slug=slug)
        ia = ImageAsset.objects.filter(addon=self.app)
        eq_(list(a.slug for a in ia), [slug])

        with storage.open(ia[0].image_path) as fp:
            im = Image.open(fp)
            im.load()
        eq_(im.size, asset['size'])

    @mock.patch('django.core.files.storage.default_storage.open',
                _mock_hide_64px_icon)
    def test_use_64(self):
        # There's an icon set up for this ID that has the path that the
        # generator would expect for a 64x64px icon. It should fallback
        # on that one, since there isn't a 128x128px icon.
        tasks.generate_image_assets(self.app)
        for asset in APP_IMAGE_SIZES:
            ia = ImageAsset.objects.get(addon=self.app,
                                        slug=asset['slug'])
            with storage.open(ia.image_path) as fp:
                im = Image.open(fp)
                im.load()
            eq_(im.size, asset['size'])

    def test_get_hue(self):
        with storage.open(os.path.join(os.path.dirname(__file__),
                                       self.app.get_icon_dir(),
                                       '%d-128.png' % self.app.id)) as fp:
            im = Image.open(fp)
            im.load()
        eq_(tasks.get_hue(im), 42)


class TestFetchManifest(amo.tests.TestCase):

    def setUp(self):
        self.upload = FileUpload.objects.create()
        self.content_type = 'application/x-web-app-manifest+json'

        patcher = mock.patch('mkt.developers.tasks.urllib2.urlopen')
        self.urlopen_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def get_upload(self):
        return FileUpload.objects.get(pk=self.upload.pk)

    def file(self, name):
        return os.path.join(os.path.dirname(__file__), 'addons', name)

    @contextmanager
    def patch_urlopen(self):
        response_mock = mock.Mock()
        response_mock.read.return_value = '<default>'
        response_mock.headers = {'Content-Type': self.content_type}
        yield response_mock
        self.urlopen_mock.return_value = response_mock

    @mock.patch('mkt.developers.tasks.validator')
    def test_success_add_file(self, validator_mock):
        with self.patch_urlopen() as ur:
            ur.read.return_value = 'woo'
            ur.headers = {'Content-Type': self.content_type}

        tasks.fetch_manifest('http://xx.com/manifest.json', self.upload.pk)
        upload = FileUpload.objects.get(pk=self.upload.pk)
        eq_(upload.name, 'http://xx.com/manifest.json')
        eq_(upload.is_webapp, True)
        eq_(storage.open(upload.path).read(), 'woo')

    @mock.patch('mkt.developers.tasks.validator')
    def test_success_call_validator(self, validator_mock):
        with self.patch_urlopen() as ur:
            ct = self.content_type + '; charset=utf-8'
            ur.headers = {'Content-Type': ct}

        tasks.fetch_manifest('http://xx.com/manifest.json', self.upload.pk)
        assert validator_mock.called

    def check_validation(self, msg=''):
        upload = self.get_upload()
        if msg:
            validation = json.loads(upload.validation)
            eq_([m['message'] for m in validation['messages']], [msg])
            eq_(validation['errors'], 1)
            eq_(validation['success'], False)
            eq_(len(validation['messages']), 1)
        else:
            validation_output = upload.validation
            if not validation_output:
                return
            validation = json.loads(validation_output)
            assert not validation['messages']
            eq_(validation['errors'], 0)
            eq_(validation['success'], True)

    def test_connection_error(self):
        reason = socket.gaierror(8, 'nodename nor servname provided')
        self.urlopen_mock.side_effect = urllib2.URLError(reason)
        tasks.fetch_manifest('url', self.upload.pk)
        self.check_validation(
            'No manifest was found at that URL. Check the address and try '
            'again.')

    def test_url_timeout(self):
        reason = socket.timeout('too slow')
        self.urlopen_mock.side_effect = urllib2.URLError(reason)
        tasks.fetch_manifest('url', self.upload.pk)
        self.check_validation(
            'No manifest was found at that URL. Check the address and try '
            'again.')

    def test_other_url_error(self):
        reason = Exception('Some other failure.')
        self.urlopen_mock.side_effect = urllib2.URLError(reason)
        tasks.fetch_manifest('url', self.upload.pk)
        self.check_validation(
            'No manifest was found at that URL. Check the address and try '
            'again.')

    @mock.patch('mkt.developers.tasks.validator', lambda uid, **kw: None)
    def test_no_content_type(self):
        with self.patch_urlopen() as ur:
            ur.headers = {}

        tasks.fetch_manifest('url', self.upload.pk)
        self.check_validation(
            'Manifests must be served with the HTTP header "Content-Type: '
            'application/x-web-app-manifest+json". See %s for more '
            'information.' % tasks.CT_URL)

    @mock.patch('mkt.developers.tasks.validator', lambda uid, **kw: None)
    def test_bad_content_type(self):
        with self.patch_urlopen() as ur:
            ur.headers = {'Content-Type': 'x'}

        tasks.fetch_manifest('url', self.upload.pk)
        self.check_validation(
            'Manifests must be served with the HTTP header "Content-Type: '
            'application/x-web-app-manifest+json". See %s for more '
            'information.' % tasks.CT_URL)

    @mock.patch('mkt.developers.tasks.validator', lambda uid, **kw: None)
    def test_good_charset(self):
        with self.patch_urlopen() as ur:
            ur.headers = {
                'Content-Type': 'application/x-web-app-manifest+json;'
                                'charset=utf-8'}

        tasks.fetch_manifest('url', self.upload.pk)
        self.check_validation()

    @mock.patch('mkt.developers.tasks.validator', lambda uid, **kw: None)
    def test_bad_charset(self):
        with self.patch_urlopen() as ur:
            ur.headers = {
                'Content-Type': 'application/x-web-app-manifest+json;'
                                'charset=ISO-1234567890-LOL'}

        tasks.fetch_manifest('url', self.upload.pk)
        self.check_validation("The manifest's encoding does not match the "
                              'charset provided in the HTTP Content-Type.')

    def test_response_too_large(self):
        with self.patch_urlopen() as ur:
            content = 'x' * (settings.MAX_WEBAPP_UPLOAD_SIZE + 1)
            ur.read.return_value = content

        tasks.fetch_manifest('url', self.upload.pk)
        max_webapp_size = settings.MAX_WEBAPP_UPLOAD_SIZE
        self.check_validation('Your manifest must be less than %s bytes.' %
                              max_webapp_size)

    def test_http_error(self):
        self.urlopen_mock.side_effect = urllib2.HTTPError(
            'url', 404, 'Not Found', [], None)
        tasks.fetch_manifest('url', self.upload.pk)
        self.check_validation(
            'No manifest was found at that URL. Check the address and try '
            'again.')

    def test_strip_utf8_bom(self):
        with self.patch_urlopen() as ur:
            with open(self.file('utf8bom.webapp')) as fp:
                ur.read.return_value = fp.read()

        tasks.fetch_manifest('url', self.upload.pk)
        upload = self.get_upload()
        with storage.open(upload.path, 'rb') as fp:
            manifest = fp.read()
            json.loads(manifest)  # no parse error
            assert not manifest.startswith(codecs.BOM_UTF8)

    def test_non_utf8_encoding(self):
        with self.patch_urlopen() as ur:
            with open(self.file('utf8bom.webapp')) as fp:
                # Set encoding to utf16 which will be invalid
                ur.read.return_value = fp.read().decode('utf8').encode('utf16')
        tasks.fetch_manifest('url', self.upload.pk)
        self.check_validation(
                    'Your manifest file was not encoded as valid UTF-8.')


class TestFetchIcon(BaseWebAppTest):

    def setUp(self):
        super(TestFetchIcon, self).setUp()
        self.content_type = 'image/png'
        self.apps_path = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                                      'addons')
        patcher = mock.patch('mkt.developers.tasks.urllib2.urlopen')
        self.urlopen_mock = patcher.start()
        self.urlopen_mock.return_value = StringIO('mozballin')
        self.addCleanup(patcher.stop)

    def webapp_from_path(self, path):
        self.upload = self.get_upload(abspath=path)
        self.url = reverse('submit.app')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        return self.post_addon()

    def test_no_version(self):
        app = Webapp()
        eq_(tasks.fetch_icon(app), None)

    def test_no_icons(self):
        path = os.path.join(self.apps_path, 'noicon.webapp')
        iconless_app = self.webapp_from_path(path)
        tasks.fetch_icon(iconless_app)
        assert not self.urlopen_mock.called

    def test_bad_icons(self):
        path = os.path.join(self.apps_path, 'badicon.webapp')
        iconless_app = self.webapp_from_path(path)
        tasks.fetch_icon(iconless_app)
        assert not self.urlopen_mock.called

    def check_icons(self, webapp):
        manifest = webapp.get_manifest_json()
        biggest = max([int(size) for size in manifest['icons']])

        icon_dir = webapp.get_icon_dir()
        for size in amo.ADDON_ICON_SIZES:
            if not size <= biggest:
                continue
            icon_path = os.path.join(icon_dir, '%s-%s.png'
                                     % (str(webapp.id), size))
            with open(icon_path, 'r') as img:
                checker = ImageCheck(img)
                assert checker.is_image()
                eq_(checker.img.size, (size, size))

    def test_data_uri(self):
        app_path = os.path.join(self.apps_path, 'dataicon.webapp')
        webapp = self.webapp_from_path(app_path)

        tasks.fetch_icon(webapp)
        eq_(webapp.icon_type, self.content_type)

        self.check_icons(webapp)

    def test_hosted_icon(self):
        app_path = os.path.join(self.apps_path, 'mozball.webapp')
        webapp = self.webapp_from_path(app_path)

        img_path = os.path.join(self.apps_path, 'mozball-128.png')
        with open(img_path, 'r') as content:
            tasks.save_icon(webapp, content.read())
        eq_(webapp.icon_type, self.content_type)

        self.check_icons(webapp)

    @mock.patch('mkt.developers.tasks._fetch_content')
    @mock.patch('mkt.developers.tasks.save_icon')
    def test_cdn_icon(self, save, fetch):
        response = mock.Mock()
        response.read.return_value = ''
        webapp = mock.Mock()
        webapp.is_packaged = False
        url = 'http://foo.com/bar'
        webapp.get_manifest_json.return_value = {'icons': {'128': url}}
        tasks.fetch_icon(webapp)
        assert url in fetch.call_args[0][0]

    @mock.patch('mkt.developers.tasks.SafeUnzip')
    @mock.patch('mkt.developers.tasks.save_icon')
    def test_packaged_icon(self, save, zip):
        response = mock.Mock()
        response.read.return_value = ''
        zf = mock.Mock()
        zip.return_value = zf
        webapp = mock.Mock()
        webapp.is_packaged = True
        url = '/path/to/icon.png'
        webapp.get_manifest_json.return_value = {'icons': {'128': url}}
        tasks.fetch_icon(webapp)
        assert url[1:] in zf.extract_path.call_args[0][0]


class TestRegionEmail(amo.tests.WebappTestCase):

    @mock.patch.object(settings, 'SITE_URL', 'http://omg.org/yes')
    def test_email_for_one_new_region(self):
        tasks.region_email([self.app.id], [mkt.regions.BR])
        msg = mail.outbox[0]
        eq_(msg.subject, '%s: Brazil region added to the Firefox Marketplace'
                          % self.app.name)
        eq_(msg.to, ['steamcube@mozilla.com'])
        dev_url = ('http://omg.org/yes/developers/app/something-something/'
                   'edit#details')
        assert unicode(self.app.name) in msg.body
        assert dev_url in msg.body
        assert ' added a new ' in msg.body
        assert ' for Brazil.' in msg.body
        assert 'Unsubscribe' in msg.body

    @mock.patch.object(settings, 'SITE_URL', 'http://omg.org/yes')
    def test_email_for_two_new_regions(self):
        tasks.region_email([self.app.id],
                           [mkt.regions.UK, mkt.regions.BR])
        msg = mail.outbox[0]
        eq_(msg.subject, '%s: New regions added to the Firefox Marketplace'
                         % self.app.name)
        eq_(msg.to, ['steamcube@mozilla.com'])
        dev_url = ('http://omg.org/yes/developers/app/something-something/'
                   'edit#details')
        assert unicode(self.app.name) in msg.body
        assert dev_url in msg.body
        assert ' added two new ' in msg.body
        assert ': Brazil and United Kingdom.' in msg.body
        assert 'Unsubscribe' in msg.body

    @mock.patch.object(settings, 'SITE_URL', 'http://omg.org/yes')
    def test_email_for_several_new_regions(self):
        tasks.region_email([self.app.id],
                           [mkt.regions.UK, mkt.regions.US, mkt.regions.BR])
        msg = mail.outbox[0]
        eq_(msg.subject, '%s: New regions added to the Firefox Marketplace'
                          % self.app.name)
        assert ' added a few new ' in msg.body
        assert ': Brazil, United Kingdom, and United States.' in msg.body


class TestRegionExclude(amo.tests.WebappTestCase):

    def test_exclude_no_apps(self):
        tasks.region_exclude([], [])
        eq_(AER.objects.count(), 0)

        tasks.region_exclude([], [mkt.regions.UK])
        eq_(AER.objects.count(), 0)

    def test_exclude_no_regions(self):
        tasks.region_exclude([self.app.id], [])
        eq_(AER.objects.count(), 0)

    def test_exclude_one_new_region(self):
        tasks.region_exclude([self.app.id], [mkt.regions.UK])
        excluded = list(AER.objects.filter(addon=self.app)
                        .values_list('region', flat=True))
        eq_(excluded, [mkt.regions.UK.id])

    def test_exclude_several_new_regions(self):
        tasks.region_exclude([self.app.id], [mkt.regions.US, mkt.regions.UK])
        excluded = sorted(AER.objects.filter(addon=self.app)
                          .values_list('region', flat=True))
        eq_(excluded, sorted([mkt.regions.US.id, mkt.regions.UK.id]))
