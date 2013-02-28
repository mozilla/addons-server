import json
import os

from django.conf import settings
from django.core.files.storage import default_storage as storage

from mock import patch
from nose.tools import eq_
from nose import SkipTest
from PIL import Image
from pyquery import PyQuery as pq
import waffle

import amo
import amo.tests

from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from addons.models import Addon, Category
from users.models import UserProfile
from versions.models import License


class TestSubmitPersona(amo.tests.TestCase):
    # TODO(future employee): Make this a form test and move it to `test_forms`.
    fixtures = ['base/apps', 'base/platforms', 'base/users']

    def setUp(self):
        super(TestSubmitPersona, self).setUp()
        self.client.login(username='regular@mozilla.com', password='password')
        self.populate()
        self.url = reverse('devhub.personas.submit')
        self.patcher = patch.object(waffle, 'flag_is_active')
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def populate(self):
        self.cat = Category.objects.create(application_id=amo.FIREFOX.id,
                                           type=amo.ADDON_PERSONA, name='xxxx')
        License.objects.create(id=amo.LICENSE_CC_BY.id)

    def get_dict(self, **kw):
        data = dict(name='new name', category=self.cat.id,
                    accentcolor='#003366', textcolor='#C0FFEE',
                    summary='new summary',
                    tags='tag1, tag2, tag3',
                    license=amo.LICENSE_CC_BY.id,
                    agreed=True)
        data.update(**kw)
        return data

    def test_submit_name_unique(self):
        """Make sure name is unique."""
        Addon.objects.create(type=amo.ADDON_EXTENSION, name='Cooliris')
        for name in ('Cooliris', '  Cooliris  ', 'cooliris'):
            r = self.client.post(self.url, self.get_dict(name=name))
            self.assertFormError(r, 'form', 'name',
                'This name is already in use. Please choose another.')

    def test_submit_name_required(self):
        """Make sure name is required."""
        r = self.client.post(self.url, self.get_dict(name=''))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_submit_name_length(self):
        """Make sure the name isn't too long."""
        r = self.client.post(self.url, self.get_dict(name='a' * 51))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'name',
            'Ensure this value has at most 50 characters (it has 51).')

    def test_submit_summary_optional(self):
        """Make sure summary is required."""
        r = self.client.post(self.url, self.get_dict(summary=''))
        eq_(r.status_code, 200)
        assert 'summary' not in r.context['form'].errors, (
            'Expected no summary errors')

    def test_submit_summary_length(self):
        """Summary is too long."""
        r = self.client.post(self.url, self.get_dict(summary='a' * 251))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'summary',
            'Ensure this value has at most 250 characters (it has 251).')

    def test_submit_categories_required(self):
        r = self.client.post(self.url, self.get_dict(category=''))
        eq_(r.context['form'].errors['category'], ['This field is required.'])

    def test_license_required(self):
        r = self.client.post(self.url, self.get_dict(license=''))
        self.assertFormError(r, 'form', 'license',
                             'A license must be selected.')

    def test_header_hash_required(self):
        r = self.client.post(self.url, self.get_dict(header_hash=''))
        self.assertFormError(r, 'form', 'header_hash',
                             'This field is required.')

    def test_footer_hash_required(self):
        r = self.client.post(self.url, self.get_dict(footer_hash=''))
        self.assertFormError(r, 'form', 'footer_hash',
                             'This field is required.')

    def test_accentcolor_optional(self):
        r = self.client.post(self.url, self.get_dict(accentcolor=''))
        assert 'accentcolor' not in r.context['form'].errors, (
            'Expected no accentcolor errors')

    def test_accentcolor_invalid(self):
        r = self.client.post(self.url, self.get_dict(accentcolor='#BALLIN'))
        self.assertFormError(r, 'form', 'accentcolor',
            'This must be a valid hex color code, such as #000000.')

    def test_textcolor_optional(self):
        r = self.client.post(self.url, self.get_dict(textcolor=''))
        assert 'textcolor' not in r.context['form'].errors, (
            'Expected no textcolor errors')

    def test_textcolor_invalid(self):
        r = self.client.post(self.url, self.get_dict(textcolor='#BALLIN'))
        self.assertFormError(r, 'form', 'textcolor',
            'This must be a valid hex color code, such as #000000.')

    def get_img_urls(self):
        return (
            reverse('devhub.personas.upload_persona', args=['persona_header']),
            reverse('devhub.personas.upload_persona', args=['persona_footer'])
        )

    def test_img_urls(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        header_url, footer_url = self.get_img_urls()
        eq_(doc('#id_header').attr('data-upload-url'), header_url)
        eq_(doc('#id_footer').attr('data-upload-url'), footer_url)

    def test_img_size(self):
        img = get_image_path('mozilla.png')
        for url, img_type in zip(self.get_img_urls(), ('header', 'footer')):
            r_ajax = self.client.post(url, {'upload_image': open(img, 'rb')})
            r_json = json.loads(r_ajax.content)
            w, h = amo.PERSONA_IMAGE_SIZES.get(img_type)[1]
            eq_(r_json['errors'], ['Image must be exactly %s pixels wide '
                                   'and %s pixels tall.' % (w, h)])

    def test_img_wrongtype(self):
        img = open('%s/js/impala/global.js' % settings.MEDIA_ROOT, 'rb')
        for url in self.get_img_urls():
            r_ajax = self.client.post(url, {'upload_image': img})
            r_json = json.loads(r_ajax.content)
            eq_(r_json['errors'], ['Images must be either PNG or JPG.'])

    def test_success(self):
        if not hasattr(Image.core, 'jpeg_encoder'):
            raise SkipTest

        data = self.get_dict()
        header_url, footer_url = self.get_img_urls()

        img = open(get_image_path('persona-header.jpg'), 'rb')
        r_ajax = self.client.post(header_url, {'upload_image': img})
        data.update(header_hash=json.loads(r_ajax.content)['upload_hash'])

        img = open(get_image_path('persona-footer.jpg'), 'rb')
        r_ajax = self.client.post(footer_url, {'upload_image': img})
        data.update(footer_hash=json.loads(r_ajax.content)['upload_hash'])

        r = self.client.post(self.url, data)
        addon = Addon.objects.order_by('-id')[0]
        persona = addon.persona

        done_url = reverse('devhub.personas.submit.done', args=[addon.slug])
        self.assertRedirects(r, done_url, 302)

        # Test for correct Addon and Persona values.
        eq_(unicode(addon.name), data['name'])

        self.assertSetEqual(addon.categories.values_list('id', flat=True),
                            [self.cat.id])

        tags = ', '.join(sorted(addon.tags.values_list('tag_text', flat=True)))
        eq_(tags, data['tags'])

        eq_(persona.persona_id, 0)
        eq_(persona.license_id, data['license'])

        eq_(persona.accentcolor, data['accentcolor'].lstrip('#'))
        eq_(persona.textcolor, data['textcolor'].lstrip('#'))

        user = UserProfile.objects.get(pk=999)
        eq_(persona.author, user.name)
        eq_(persona.display_username, user.username)

        v = addon.versions.all()
        eq_(len(v), 1)
        eq_(v[0].version, '0')

        # Test for header, footer, and preview images.
        dst = os.path.join(settings.PERSONAS_PATH, str(addon.id))

        img = os.path.join(dst, 'header.png')
        eq_(persona.header, 'header.png')
        eq_(storage.exists(img), True)
        eq_(Image.open(storage.open(img)).size, (3000, 200))
        eq_(amo.PERSONA_IMAGE_SIZES['header'][1], (3000, 200))

        img = os.path.join(dst, 'footer.png')
        eq_(persona.footer, 'footer.png')
        eq_(storage.exists(img), True)
        eq_(Image.open(storage.open(img)).size, (3000, 100))
        eq_(amo.PERSONA_IMAGE_SIZES['footer'][1], (3000, 100))

        img = os.path.join(dst, 'preview.png')
        eq_(storage.exists(img), True)
        eq_(Image.open(storage.open(img)).size, (680, 100))
        eq_(amo.PERSONA_IMAGE_SIZES['header'][0], (680, 100))
