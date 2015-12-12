import json

from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse


class TestSubmitPersona(amo.tests.TestCase):
    fixtures = ['base/user_999']

    def setUp(self):
        super(TestSubmitPersona, self).setUp()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.url = reverse('devhub.themes.submit')

    def get_img_urls(self):
        return (
            reverse('devhub.personas.upload_persona', args=['persona_header']),
            reverse('devhub.personas.upload_persona', args=['persona_footer'])
        )

    def test_img_urls(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        doc = pq(r.content)
        header_url, footer_url = self.get_img_urls()
        assert doc('#id_header').attr('data-upload-url') == header_url
        assert doc('#id_footer').attr('data-upload-url') == footer_url

    def test_img_size(self):
        img = get_image_path('mozilla.png')
        for url, img_type in zip(self.get_img_urls(), ('header', 'footer')):
            r_ajax = self.client.post(url, {'upload_image': open(img, 'rb')})
            r_json = json.loads(r_ajax.content)
            w, h = amo.PERSONA_IMAGE_SIZES.get(img_type)[1]
            assert r_json['errors'] == ['Image must be exactly %s pixels wide ' 'and %s pixels tall.' % (w, h)]

    def test_img_wrongtype(self):
        img = open('static/js/impala/global.js', 'rb')
        for url in self.get_img_urls():
            r_ajax = self.client.post(url, {'upload_image': img})
            r_json = json.loads(r_ajax.content)
            assert r_json['errors'] == ['Images must be either PNG or JPG.']
