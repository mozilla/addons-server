import json

from django.conf import settings

from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests

from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse


class TestSubmitPersona(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/user_999']

    def setUp(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.url = reverse('devhub.themes.submit')

    def get_img_urls(self):
        return (
            reverse('devhub.personas.upload_persona', args=['persona_header']),
            reverse('devhub.personas.upload_persona', args=['persona_footer'])
        )

    def test_img_urls(self):
        self.create_flag('submit-personas')
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
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
