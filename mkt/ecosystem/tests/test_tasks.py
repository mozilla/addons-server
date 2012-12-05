import mock
from nose.tools import eq_

from django.http import Http404

import amo.tests
from gelato.models.mkt.ecosystem import MdnCache
from mkt.ecosystem.tasks import _fetch_mdn_page, _update_mdn_items, locales


test_items = [
    {
        'title': 'Test Mdn Page',
        'name': 'test',
        'locale': 'en-US',
        'mdn': 'https://developer.mozilla.org/%(locale)s/HTML/HTML5?raw=1'
               '&macros=true'
    }
]


def fake_page(url):
    return """<section id='article-nav'>
                    <div class='page-toc'>
                        <ol>
                            <li><script>alert('xss');</script></li>
                        </ol>
                    </div>
                </section>
                <section id='pageText'>
                    <b>hi</b><script>alert('xss');</script>
                    <a href="/relative/url">some MDN link</a>
                    <a href="http://www.youtube.com/1234"
                       class="video-item">Some Youtube link</a>
                    <img src="/relative/url">
                </section>"""


def raise_exception(url):
    raise Exception('test')


def raise_404(url):
    raise Http404


class TestMdnCacheUpdate(amo.tests.TestCase):
    fixtures = ['ecosystem/mdncache-item']

    def setUp(self):
        for item in test_items:
            item['url'] = item['mdn'] % {'locale': 'en-US'}

    @mock.patch('mkt.ecosystem.tasks._get_page', new=fake_page)
    def test_refresh_mdn_cache(self):
        _update_mdn_items(test_items)
        eq_('test', MdnCache.objects.get(name=test_items[0]['name'],
                                         locale='en-US').name)

    @mock.patch('mkt.ecosystem.tasks._get_page', new=fake_page)
    def test_refresh_mdn_cache_with_old_data(self):
        eq_('old', MdnCache.objects.get(name='old',
                                        locale='en-US').name)
        _update_mdn_items(test_items)
        eq_('test', MdnCache.objects.get(name=test_items[0]['name'],
                                         locale='en-US').name)
        self.assertSetEqual(list(MdnCache.objects.values_list('locale', flat=True)), locales)

        with self.assertRaises(MdnCache.DoesNotExist):
            MdnCache.objects.get(name='old', locale='en-US')

    @mock.patch('mkt.ecosystem.tasks._get_page', new=fake_page)
    def test_ensure_content_xss_safe(self):
        content = _fetch_mdn_page(test_items[0]['url'])
        assert '<script>' not in content
        assert '&lt;script&gt;alert' in content
        assert '<b>hi</b>' in content

    @mock.patch('mkt.ecosystem.tasks._get_page', new=fake_page)
    def test_ensure_relative_link_is_absolute(self):
        content = _fetch_mdn_page(test_items[0]['url'])
        assert '<a href="/relative/url">' not in content
        assert('<a href="https://developer.mozilla.org/relative/url'
                in content)

    @mock.patch('mkt.ecosystem.tasks._get_page', new=fake_page)
    def test_ensure_relative_image_is_absolute(self):
        content = _fetch_mdn_page(test_items[0]['url'])
        assert '<img src="/relative/url">' not in content
        assert('<img src="https://developer.mozilla.org/relative/url'
                in content)

    @mock.patch('mkt.ecosystem.tasks._get_page', new=fake_page)
    def test_returns_embedded_video(self):
        content = _fetch_mdn_page(test_items[0]['url'])
        assert('<a href="http://www.youtube.com/1234" '
                'class="video-embed">Some Youtube link</a>'
                not in content)
        assert('<iframe frameborder="0" width="640" height="360" '
               'src="http://www.youtube.com/1234"'
                in content)

    @mock.patch('mkt.ecosystem.tasks._get_page', new=raise_exception)
    def test_dont_delete_on_exception(self):
        with self.assertRaises(Exception):
            _update_mdn_items(test_items)
            eq_(2, MdnCache.objects.count())

    @mock.patch('mkt.ecosystem.tasks._get_page', new=raise_404)
    def test_continue_on_404_exception(self):
        _update_mdn_items(test_items)
        eq_(0, MdnCache.objects.count())
