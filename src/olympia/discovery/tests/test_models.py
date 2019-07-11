from unittest import mock

from django.http import QueryDict
from django.test.utils import override_settings

from olympia import amo
from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.discovery.models import DiscoveryItem


class TestDiscoveryItem(TestCase):
    def test_heading_multiple_authors(self):
        addon = addon_factory(slug=u'somé-slug', name=u'Sôme Name')
        user1 = user_factory(display_name=u'Bàr')
        addon.addonuser_set.create(user=user1, position=1)
        user2 = user_factory(username=u'Fôo', id=345)
        addon.addonuser_set.create(user=user2, position=2)
        user3 = user_factory(username=u'Nôpe')
        addon.addonuser_set.create(user=user3, listed=False)

        item = DiscoveryItem.objects.create(
            addon=addon,
            custom_heading=(u'Fancy Héading {start_sub_heading}with '
                            u'{addon_name}{end_sub_heading}'))
        assert item.heading == (
            u'Fancy Héading <span>with '
            u'<a href="http://testserver/en-US/firefox/addon/som%C3%A9-slug/'
            u'?{}">'
            u'Sôme Name by Bàr, Firefox user 345</a></span>').format(
                item.build_querystring())

    def test_heading_custom(self):
        addon = addon_factory(slug=u'somé-slug', name=u'Sôme Name')
        user = user_factory(display_name=u'Fløp')
        addon.addonuser_set.create(user=user)
        item = DiscoveryItem.objects.create(
            addon=addon,
            custom_heading=(u'Fancy Héading {start_sub_heading}with '
                            u'{addon_name}{end_sub_heading}'))
        assert item.heading == (
            u'Fancy Héading <span>with '
            u'<a href="http://testserver/en-US/firefox/addon/som%C3%A9-slug/'
            u'?{}">'
            u'Sôme Name by Fløp</a></span>').format(item.build_querystring())

    def test_heading_custom_xss(self):
        # Custom heading itself should not contain HTML; only the special {xxx}
        # tags we explicitely support.
        addon = addon_factory(
            slug=u'somé-slug', name=u'<script>alert(42)</script>')
        user = user_factory(display_name=u'<script>alert(666)</script>')
        addon.addonuser_set.create(user=user)
        item = DiscoveryItem.objects.create(
            addon=addon,
            custom_heading=u'<script>alert(0)</script>{addon_name}')
        assert item.heading == (
            u'&lt;script&gt;alert(0)&lt;/script&gt;'
            u'<a href="http://testserver/en-US/firefox/addon/som%C3%A9-slug/'
            u'?{}">'
            u'&lt;script&gt;alert(42)&lt;/script&gt; '
            u'by &lt;script&gt;alert(666)&lt;/script&gt;</a>').format(
                item.build_querystring())

    def test_heading_non_custom(self):
        addon = addon_factory(slug=u'somé-slug', name=u'Sôme Name')
        addon.addonuser_set.create(user=user_factory(display_name=u'Fløp'))
        item = DiscoveryItem.objects.create(addon=addon)
        assert item.heading == (
            u'Sôme Name <span>by '
            u'<a href="http://testserver/en-US/firefox/addon/som%C3%A9-slug/'
            u'?{}">'
            u'Fløp</a></span>').format(item.build_querystring())

    def test_heading_non_custom_xss(self):
        addon = addon_factory(
            slug=u'somé-slug', name=u'<script>alert(43)</script>')
        user = user_factory(display_name=u'<script>alert(667)</script>')
        addon.addonuser_set.create(user=user)
        item = DiscoveryItem.objects.create(addon=addon)
        assert item.heading == (
            u'&lt;script&gt;alert(43)&lt;/script&gt; <span>by '
            u'<a href="http://testserver/en-US/firefox/addon/som%C3%A9-slug/'
            u'?{}">'
            u'&lt;script&gt;alert(667)&lt;/script&gt;</a></span>').format(
                item.build_querystring())

    def test_heading_custom_with_custom_addon_name(self):
        addon = addon_factory(slug=u'somé-slug')
        addon.addonuser_set.create(user=user_factory(display_name=u'Fløp'))
        item = DiscoveryItem.objects.create(
            addon=addon, custom_addon_name=u'Custôm Name',
            custom_heading=(u'Fancy Héading {start_sub_heading}with '
                            u'{addon_name}{end_sub_heading}'))
        assert item.heading == (
            u'Fancy Héading <span>with '
            u'<a href="http://testserver/en-US/firefox/addon/som%C3%A9-slug/'
            u'?{}">'
            u'Custôm Name by Fløp</a></span>').format(item.build_querystring())

    def test_heading_custom_with_custom_addon_name_xss(self):
        addon = addon_factory(slug=u'somé-slug')
        user = user_factory(display_name=u'<script>alert(668)</script>')
        addon.addonuser_set.create(user=user)
        item = DiscoveryItem.objects.create(
            addon=addon, custom_addon_name=u'Custôm Name',
            custom_heading=(u'Fancy Héading {start_sub_heading}with '
                            u'{addon_name}{end_sub_heading}'))
        item.custom_addon_name = '<script>alert(2)</script>'
        item.custom_heading = '<script>alert(2)</script>{addon_name}'
        assert item.heading == (
            u'&lt;script&gt;alert(2)&lt;/script&gt;'
            u'<a href="http://testserver/en-US/firefox/addon/som%C3%A9-slug/'
            u'?{}">'
            u'&lt;script&gt;alert(2)&lt;/script&gt; '
            u'by &lt;script&gt;alert(668)&lt;/script&gt;</a>').format(
                item.build_querystring())

    def test_heading_non_custom_but_with_custom_addon_name(self):
        addon = addon_factory(slug=u'somé-slug')
        addon.addonuser_set.create(user=user_factory(display_name=u'Fløp'))
        item = DiscoveryItem.objects.create(
            addon=addon, custom_addon_name=u'Custôm Name')
        assert item.heading == (
            u'Custôm Name <span>by '
            u'<a href="http://testserver/en-US/firefox/addon/som%C3%A9-slug/'
            u'?{}">'
            u'Fløp</a></span>').format(item.build_querystring())

    def test_heading_non_custom_but_with_custom_addon_name_xss(self):
        addon = addon_factory(slug=u'somé-slug')
        user = user_factory(display_name=u'<script>alert(669)</script>')
        addon.addonuser_set.create(user=user)
        item = DiscoveryItem.objects.create(
            addon=addon, custom_addon_name=u'<script>alert(3)</script>')
        assert item.heading == (
            u'&lt;script&gt;alert(3)&lt;/script&gt; <span>by '
            u'<a href="http://testserver/en-US/firefox/addon/som%C3%A9-slug/'
            u'?{}">'
            u'&lt;script&gt;alert(669)&lt;/script&gt;</a></span>').format(
                item.build_querystring())

    def test_heading_text(self):
        addon = addon_factory(slug='somé-slug', name='Sôme Name')
        user = user_factory(display_name='Fløp')
        addon.addonuser_set.create(user=user)
        item = DiscoveryItem.objects.create(addon=addon)
        assert item.heading_text == 'Sôme Name'

    def test_heading_text_custom_addon_name(self):
        addon = addon_factory(slug='somé-slug', name='Sôme Name')
        user = user_factory(display_name='Fløp')
        addon.addonuser_set.create(user=user)
        item = DiscoveryItem.objects.create(
            addon=addon, custom_addon_name='Custôm Name')
        assert item.heading_text == 'Custôm Name'

    def test_heading_text_custom(self):
        addon = addon_factory(slug='somé-slug', name=u'Sôme Name')
        user = user_factory(display_name='Fløp')
        addon.addonuser_set.create(user=user)
        item = DiscoveryItem.objects.create(
            addon=addon,
            custom_heading=('Fancy Héading {start_sub_heading}with '
                            '{addon_name}{end_sub_heading}.'))
        assert item.heading_text == 'Fancy Héading with Sôme Name.'

    def test_heading_text_custom_with_custom_addon_name(self):
        addon = addon_factory(slug='somé-slug', name='Sôme Name')
        user = user_factory(display_name='Fløp')
        addon.addonuser_set.create(user=user)
        item = DiscoveryItem.objects.create(
            addon=addon,
            custom_addon_name='Custôm Name',
            custom_heading=('Fancy Héading {start_sub_heading}with '
                            '{addon_name}{end_sub_heading}.'))
        assert item.heading_text == 'Fancy Héading with Custôm Name.'

    def test_heading_is_translated(self):
        addon = addon_factory(slug='somé-slug', name='Sôme Name')
        user = user_factory(display_name='Fløp')
        addon.addonuser_set.create(user=user)
        item = DiscoveryItem.objects.create(
            addon=addon,
            custom_addon_name='Custôm Name',
            custom_heading=('Fancy Héading {start_sub_heading}with '
                            '{addon_name}{end_sub_heading}.'))
        with mock.patch('olympia.discovery.models.ugettext') as ugettext_mock:
            ugettext_mock.return_value = f'Trans {item.custom_heading}'
            assert item.heading_text == 'Trans Fancy Héading with Custôm Name.'
            assert item.heading.startswith('Trans Fancy Héading <span>with ')

    def test_description_custom(self):
        addon = addon_factory(summary='Foo', description='Bar')
        item = DiscoveryItem.objects.create(
            addon=addon, custom_description=u'Custôm Desc')
        assert item.description == u'<blockquote>Custôm Desc</blockquote>'

        item.custom_description = u'û<script>alert(4)</script>'
        assert item.description == (
            u'<blockquote>û&lt;script&gt;alert(4)&lt;/script&gt;</blockquote>')

    def test_description_non_custom_extension(self):
        addon = addon_factory(summary='')
        item = DiscoveryItem.objects.create(addon=addon)
        assert item.description == u''

        addon.summary = u'Mÿ Summary'
        assert item.description == u'<blockquote>Mÿ Summary</blockquote>'

    def test_description_non_custom_extension_xss(self):
        addon = addon_factory(summary=u'Mÿ <script>alert(5)</script>')
        item = DiscoveryItem.objects.create(addon=addon)
        assert item.description == (
            u'<blockquote>'
            u'Mÿ &lt;script&gt;alert(5)&lt;/script&gt;</blockquote>')

    def test_description_non_custom_fallback(self):
        item = DiscoveryItem.objects.create(addon=addon_factory(
            type=amo.ADDON_DICT))
        assert item.description == u''

    def test_description_text_custom(self):
        addon = addon_factory(summary='Foo', description='Bar')
        item = DiscoveryItem.objects.create(
            addon=addon, custom_description='Custôm Desc.')
        assert item.description_text == 'Custôm Desc.'

    def test_description_text_non_custom_extension(self):
        addon = addon_factory(summary='')
        item = DiscoveryItem.objects.create(addon=addon)
        assert item.description_text == ''

        addon.summary = 'Mÿ Summary'
        assert item.description_text == 'Mÿ Summary'

    def test_description_text_non_custom_fallback(self):
        item = DiscoveryItem.objects.create(addon=addon_factory(
            type=amo.ADDON_DICT))
        assert item.description_text == ''

    @override_settings(DOMAIN='addons.mozilla.org')
    def test_build_querystring(self):
        item = DiscoveryItem.objects.create(addon=addon_factory(
            type=amo.ADDON_DICT))
        # We do not use `urlencode()` and a string comparison because QueryDict
        # does not preserve ordering.
        q = QueryDict(item.build_querystring())
        assert q.get('utm_source') == 'discovery.addons.mozilla.org'
        assert q.get('utm_medium') == 'firefox-browser'
        assert q.get('utm_content') == 'discopane-entry-link'
        assert q.get('src') == 'api'

    def test_recommended_status(self):
        item = DiscoveryItem.objects.create(addon=addon_factory())
        assert item.recommended_status == DiscoveryItem.NOT_RECOMMENDED

        item.update(recommendable=True)
        assert item.recommended_status == DiscoveryItem.PENDING_RECOMMENDATION

        item.addon.current_version.update(recommendation_approved=True)
        assert item.recommended_status == DiscoveryItem.RECOMMENDED

        item.update(recommendable=False)
        assert item.recommended_status == DiscoveryItem.NOT_RECOMMENDED
