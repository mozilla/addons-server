from datetime import datetime, timedelta
import os

from django.conf import settings
from django.core.files.storage import default_storage as storage

import fudge
from fudge.inspector import arg
from nose.tools import eq_
from requests.exceptions import RequestException

from amo.tests import TestCase

from mkt.webpay import tasks
from mkt.webpay.models import ProductIcon


class TestFetchProductIcon(TestCase):

    def fetch(self, url='http://site/media/my.jpg', ext_size=512, size=64):
        tasks.fetch_product_icon(url, ext_size, size)

    def open_img(self):
        img = open(os.path.join(os.path.dirname(__file__),
                                'resources', 'product.jpg'), 'rb')
        self.addCleanup(img.close)
        return img

    @fudge.patch('mkt.webpay.tasks.requests')
    def test_ignore_error(self, fake_req):
        (fake_req.expects('get')
                 .raises(RequestException('some error')))
        self.fetch()
        eq_(ProductIcon.objects.count(), 0)

    @fudge.patch('mkt.webpay.tasks.requests')
    def test_ignore_valid_image(self, fake_req):
        url = 'http://site/my.jpg'
        ext_size = 512
        size = 64
        ProductIcon.objects.create(ext_url=url, size=size, ext_size=ext_size)
        self.fetch(url, ext_size, size)

    @fudge.patch('mkt.webpay.tasks.requests')
    def test_refetch_old_image(self, fake_req):
        url = 'http://site/media/my.jpg'
        ext_size = 512
        now = datetime.now()
        old = now - timedelta(days=settings.PRODUCT_ICON_EXPIRY + 1)
        prod = ProductIcon.objects.create(ext_url=url, size=64,
                                          ext_size=ext_size)
        prod.update(modified=old)
        (fake_req.expects('get').returns_fake().expects('iter_content')
                                               .returns(self.open_img())
                                               .expects('raise_for_status'))
        self.fetch(url, ext_size)

    @fudge.patch('mkt.webpay.tasks.requests')
    def test_jpg_extension(self, fake_req):
        url = 'http://site/media/my.jpg'
        (fake_req.expects('get').returns_fake().expects('iter_content')
                                               .returns(self.open_img())
                                               .expects('raise_for_status'))
        self.fetch(url)
        prod = ProductIcon.objects.get()
        for fn in (prod.storage_path, prod.url):
            assert fn().endswith('.jpg'), (
                'The CDN only whitelists .jpg not .jpeg. Got: %s' % fn())

    @fudge.patch('mkt.webpay.tasks.requests')
    def test_ignore_non_image(self, fake_req):
        im = open(__file__)
        (fake_req.expects('get').returns_fake().expects('iter_content')
                                               .returns(im)
                                               .expects('raise_for_status'))
        self.fetch()
        eq_(ProductIcon.objects.count(), 0)

    @fudge.patch('mkt.webpay.tasks.requests')
    def test_fetch_ok(self, fake_req):
        url = 'http://site/media/my.jpg'
        ext_size = 512
        size = 64
        (fake_req.expects('get')
                 .with_args(url, timeout=arg.any())
                 .returns_fake()
                 .expects('iter_content')
                 .returns(self.open_img())
                 .expects('raise_for_status'))
        self.fetch(url, ext_size, size)
        prod = ProductIcon.objects.get()
        eq_(prod.ext_size, ext_size)
        eq_(prod.size, size)
        assert storage.exists(prod.storage_path()), 'Image not created'

    @fudge.patch('mkt.webpay.tasks.requests')
    @fudge.patch('mkt.webpay.tasks._resize_image')
    def test_no_resize_when_exact(self, fake_req, resize):
        url = 'http://site/media/my.jpg'
        (fake_req.expects('get')
                 .returns_fake()
                 .expects('iter_content')
                 .returns(self.open_img())
                 .expects('raise_for_status'))
        size = 64
        self.fetch(url=url, ext_size=size, size=size)
        prod = ProductIcon.objects.get()
        eq_(prod.size, size)
        assert storage.exists(prod.storage_path()), 'Image not created'

    @fudge.patch('mkt.webpay.tasks.requests')
    @fudge.patch('mkt.webpay.tasks._resize_image')
    def test_no_resize_when_smaller(self, fake_req, resize):
        url = 'http://site/media/my.jpg'
        (fake_req.expects('get')
                 .returns_fake()
                 .expects('iter_content')
                 .returns(self.open_img())
                 .expects('raise_for_status'))

        size = 22
        self.fetch(url=url, ext_size=size, size=64)
        prod = ProductIcon.objects.get()
        eq_(prod.size, size)
        eq_(prod.ext_size, size)
        assert storage.exists(prod.storage_path()), 'Image not created'
