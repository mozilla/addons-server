from datetime import datetime
from xml.dom import minidom

from django.conf import settings
from django.core.cache import cache

import test_utils
from nose.tools import eq_

import amo
import amo.tests
from amo.urlresolvers import reverse
from .models import (BlocklistApp, BlocklistDetail, BlocklistItem,
                     BlocklistGfx, BlocklistPlugin)


base_xml = """
<?xml version="1.0"?>
<blocklist xmlns="http://www.mozilla.org/2006/addons-blocklist">
</blocklist>
"""


class BlocklistTest(amo.tests.RedisTest, test_utils.TestCase):

    def setUp(self):
        super(BlocklistTest, self).setUp()
        self.fx4_url = reverse('blocklist', args=[3, amo.FIREFOX.guid, '4.0'])
        self.fx2_url = reverse('blocklist', args=[2, amo.FIREFOX.guid, '2.0'])
        self.mobile_url = reverse('blocklist', args=[2, amo.MOBILE.guid, '.9'])
        cache.clear()
        self.details = BlocklistDetail.objects.create()

    def normalize(self, s):
        return '\n'.join(x.strip() for x in s.split())

    def eq_(self, x, y):
        return eq_(self.normalize(x), self.normalize(y))

    def dom(self, url):
        r = self.client.get(url)
        return minidom.parseString(r.content)


class BlocklistItemTest(BlocklistTest):

    def setUp(self):
        super(BlocklistItemTest, self).setUp()
        self.item = BlocklistItem.objects.create(guid='guid@addon.com',
                                                 details=self.details)
        self.app = BlocklistApp.objects.create(blitem=self.item,
                                               guid=amo.FIREFOX.guid)

    def test_content_type(self):
        response = self.client.get(self.fx4_url)
        eq_(response['Content-Type'], 'text/xml')

    def test_empty_string_goes_null_on_save(self):
        b = BlocklistItem(guid='guid', min='', max='', os='')
        b.save()
        assert b.min is None
        assert b.max is None
        assert b.os is None

    def test_lastupdate(self):
        def eq(a, b):
            eq_(a, b.replace(microsecond=0))

        def find_lastupdate():
            bl = self.dom(self.fx4_url).getElementsByTagName('blocklist')[0]
            t = int(bl.getAttribute('lastupdate')) / 1000
            return datetime.fromtimestamp(t)

        eq(find_lastupdate(), self.item.created)

        self.item.save()
        eq(find_lastupdate(), self.item.modified)

        plugin = BlocklistPlugin.objects.create(guid=amo.FIREFOX.guid)
        eq(find_lastupdate(), plugin.created)
        plugin.save()
        eq(find_lastupdate(), plugin.modified)

        gfx = BlocklistGfx.objects.create(guid=amo.FIREFOX.guid)
        eq(find_lastupdate(), gfx.created)
        gfx.save()
        eq(find_lastupdate(), gfx.modified)

        assert (self.item.created != self.item.modified != plugin.created
                != plugin.modified != gfx.created != gfx.modified)

    def test_no_items(self):
        self.item.delete()
        dom = self.dom(self.fx4_url)
        children = dom.getElementsByTagName('blocklist')[0].childNodes
        # There are only text nodes.
        assert all(e.nodeType == 3 for e in children)

    def test_new_cookie_per_user(self):
        self.client.get(self.fx4_url)
        assert settings.BLOCKLIST_COOKIE in self.client.cookies
        c = self.client.cookies[settings.BLOCKLIST_COOKIE]
        eq_(c['path'], '/blocklist/')
        eq_(c['secure'], True)

    def test_existing_user_cookie(self):
        self.client.cookies[settings.BLOCKLIST_COOKIE] = 'adfadf'
        self.client.get(self.fx4_url)
        eq_(self.client.cookies[settings.BLOCKLIST_COOKIE].value, 'adfadf')

    def test_url_params(self):
        eq_(self.client.get(self.fx4_url).status_code, 200)
        eq_(self.client.get(self.fx2_url).status_code, 200)
        # We ignore trailing url parameters.
        eq_(self.client.get(self.fx4_url + 'other/junk/').status_code, 200)

    def test_app_guid(self):
        # There's one item for Firefox.
        r = self.client.get(self.fx4_url)
        eq_(r.status_code, 200)
        eq_(len(r.context['items']), 1)

        # There are no items for mobile.
        r = self.client.get(self.mobile_url)
        eq_(r.status_code, 200)
        eq_(len(r.context['items']), 0)

        # Without the app constraint we see the item.
        self.app.delete()
        r = self.client.get(self.mobile_url)
        eq_(r.status_code, 200)
        eq_(len(r.context['items']), 1)

    def test_item_guid(self):
        items = self.dom(self.fx4_url).getElementsByTagName('emItem')
        eq_(len(items), 1)
        eq_(items[0].getAttribute('id'), 'guid@addon.com')

    def test_block_id(self):
        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        eq_(item.getAttribute('blockID'), 'i' + str(self.details.id))

    def test_item_os(self):
        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        assert 'os' not in item.attributes.keys()

        self.item.update(os='win,mac')
        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        eq_(item.getAttribute('os'), 'win,mac')

    def test_item_severity(self):
        self.item.update(severity=2)
        eq_(len(self.vr()), 1)
        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        vrange = item.getElementsByTagName('versionRange')
        eq_(vrange[0].getAttribute('severity'), '2')

    def vr(self):
        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        return item.getElementsByTagName('versionRange')

    def test_item_version_range(self):
        self.item.update(min='0.1')
        eq_(len(self.vr()), 1)
        eq_(self.vr()[0].attributes.keys(), ['minVersion'])
        eq_(self.vr()[0].getAttribute('minVersion'), '0.1')

        self.item.update(max='0.2')
        eq_(self.vr()[0].attributes.keys(), ['minVersion', 'maxVersion'])
        eq_(self.vr()[0].getAttribute('minVersion'), '0.1')
        eq_(self.vr()[0].getAttribute('maxVersion'), '0.2')

    def test_item_multiple_version_range(self):
        # There should be two <versionRange>s under one <emItem>.
        self.item.update(min='0.1', max='0.2')
        BlocklistItem.objects.create(guid=self.item.guid, severity=3)

        item = self.dom(self.fx4_url).getElementsByTagName('emItem')
        eq_(len(item), 1)
        vr = item[0].getElementsByTagName('versionRange')
        eq_(len(vr), 2)
        eq_(vr[0].getAttribute('minVersion'), '0.1')
        eq_(vr[0].getAttribute('maxVersion'), '0.2')
        eq_(vr[1].getAttribute('severity'), '3')

    def test_item_target_app(self):
        app = self.app
        self.app.delete()
        self.item.update(severity=2)
        version_range = self.vr()[0]
        eq_(version_range.getElementsByTagName('targetApplication'), [])

        app.save()
        version_range = self.vr()[0]
        target_app = version_range.getElementsByTagName('targetApplication')
        eq_(len(target_app), 1)
        eq_(target_app[0].getAttribute('id'), amo.FIREFOX.guid)

        app.update(min='0.1', max='*')
        version_range = self.vr()[0]
        target_app = version_range.getElementsByTagName('targetApplication')
        eq_(target_app[0].getAttribute('id'), amo.FIREFOX.guid)
        tvr = target_app[0].getElementsByTagName('versionRange')
        eq_(tvr[0].getAttribute('minVersion'), '0.1')
        eq_(tvr[0].getAttribute('maxVersion'), '*')

    def test_item_multiple_apps(self):
        # Make sure all <targetApplication>s go under the same <versionRange>.
        self.app.update(min='0.1', max='0.2')
        BlocklistApp.objects.create(guid=amo.FIREFOX.guid, blitem=self.item,
                                    min='3.0', max='3.1')
        version_range = self.vr()[0]
        apps = version_range.getElementsByTagName('targetApplication')
        eq_(len(apps), 2)
        eq_(apps[0].getAttribute('id'), amo.FIREFOX.guid)
        vr = apps[0].getElementsByTagName('versionRange')[0]
        eq_(vr.getAttribute('minVersion'), '0.1')
        eq_(vr.getAttribute('maxVersion'), '0.2')
        eq_(apps[1].getAttribute('id'), amo.FIREFOX.guid)
        vr = apps[1].getElementsByTagName('versionRange')[0]
        eq_(vr.getAttribute('minVersion'), '3.0')
        eq_(vr.getAttribute('maxVersion'), '3.1')

    def test_item_empty_version_range(self):
        # No version_range without an app, min, max, or severity.
        self.app.delete()
        self.item.update(min=None, max=None, severity=None)
        eq_(len(self.vr()), 0)

    def test_item_empty_target_app(self):
        # No empty <targetApplication>.
        self.item.update(severity=1)
        self.app.delete()
        eq_(self.dom(self.fx4_url).getElementsByTagName('targetApplication'),
            [])

    def test_item_target_empty_version_range(self):
        app = self.dom(self.fx4_url).getElementsByTagName('targetApplication')
        eq_(app[0].getElementsByTagName('versionRange'), [])


class BlocklistPluginTest(BlocklistTest):

    def setUp(self):
        super(BlocklistPluginTest, self).setUp()
        self.plugin = BlocklistPlugin.objects.create(guid=amo.FIREFOX.guid,
                                                     details=self.details)

    def test_no_plugins(self):
        dom = BlocklistTest.dom(self, self.mobile_url)
        children = dom.getElementsByTagName('blocklist')[0].childNodes
        # There are only text nodes.
        assert all(e.nodeType == 3 for e in children)

    def dom(self, url=None):
        url = url or self.fx4_url
        r = self.client.get(url)
        d = minidom.parseString(r.content)
        return d.getElementsByTagName('pluginItem')[0]

    def test_plugin_empty(self):
        eq_(self.dom().attributes.keys(), ['blockID'])
        eq_(self.dom().getElementsByTagName('match'), [])
        eq_(self.dom().getElementsByTagName('versionRange'), [])

    def test_block_id(self):
        item = self.dom(self.fx4_url)
        eq_(item.getAttribute('blockID'), 'p' + str(self.details.id))

    def test_plugin_os(self):
        self.plugin.update(os='win')
        eq_(sorted(self.dom().attributes.keys()), ['blockID', 'os'])
        eq_(self.dom().getAttribute('os'), 'win')

    def test_plugin_xpcomabi(self):
        self.plugin.update(xpcomabi='win')
        eq_(sorted(self.dom().attributes.keys()), ['blockID', 'xpcomabi'])
        eq_(self.dom().getAttribute('xpcomabi'), 'win')

    def test_plugin_name(self):
        self.plugin.update(name='flash')
        match = self.dom().getElementsByTagName('match')
        eq_(len(match), 1)
        eq_(dict(match[0].attributes.items()),
            {'name': 'name', 'exp': 'flash'})

    def test_plugin_description(self):
        self.plugin.update(description='flash')
        match = self.dom().getElementsByTagName('match')
        eq_(len(match), 1)
        eq_(dict(match[0].attributes.items()),
            {'name': 'description', 'exp': 'flash'})

    def test_plugin_filename(self):
        self.plugin.update(filename='flash')
        match = self.dom().getElementsByTagName('match')
        eq_(len(match), 1)
        eq_(dict(match[0].attributes.items()),
            {'name': 'filename', 'exp': 'flash'})

    def test_plugin_severity(self):
        self.plugin.update(severity=2)
        v = self.dom().getElementsByTagName('versionRange')[0]
        eq_(v.getAttribute('severity'), '2')

    def test_plugin_target_app(self):
        self.plugin.update(min='1', max='2')
        v = self.dom().getElementsByTagName('versionRange')[0]
        app = v.getElementsByTagName('targetApplication')[0]
        eq_(app.getAttribute('id'), amo.FIREFOX.guid)
        vr = app.getElementsByTagName('versionRange')[0]
        eq_(vr.getAttribute('minVersion'), '1')
        eq_(vr.getAttribute('maxVersion'), '2')

    def test_plugin_apiver_lt_3(self):
        self.plugin.update(severity='2')
        # No min & max so the app matches.
        e = self.dom(self.fx2_url).getElementsByTagName('versionRange')[0]
        eq_(e.getAttribute('severity'), '2')
        eq_(e.getElementsByTagName('targetApplication'), [])

        # The app version is not in range.
        self.plugin.update(min='3.0', max='4.0')
        self.assertRaises(IndexError, self.dom, self.fx2_url)

        # The app is back in range.
        self.plugin.update(min='1.1')
        e = self.dom(self.fx2_url).getElementsByTagName('versionRange')[0]
        eq_(e.getAttribute('severity'), '2')
        eq_(e.getElementsByTagName('targetApplication'), [])


class BlocklistGfxTest(BlocklistTest):

    def setUp(self):
        super(BlocklistGfxTest, self).setUp()
        self.gfx = BlocklistGfx.objects.create(
            guid=amo.FIREFOX.guid, os='os', vendor='vendor', devices='x y z',
            feature='feature', feature_status='status', details=self.details,
            driver_version='version', driver_version_comparator='compare')

    def test_no_gfx(self):
        dom = self.dom(self.mobile_url)
        children = dom.getElementsByTagName('blocklist')[0].childNodes
        # There are only text nodes.
        assert all(e.nodeType == 3 for e in children)

    def test_gfx(self):
        r = self.client.get(self.fx4_url)
        dom = minidom.parseString(r.content)
        gfx = dom.getElementsByTagName('gfxBlacklistEntry')[0]
        find = lambda e: gfx.getElementsByTagName(e)[0].childNodes[0].wholeText
        eq_(find('os'), self.gfx.os)
        eq_(find('feature'), self.gfx.feature)
        eq_(find('vendor'), self.gfx.vendor)
        eq_(find('featureStatus'), self.gfx.feature_status)
        eq_(find('driverVersion'), self.gfx.driver_version)
        eq_(find('driverVersionComparator'),
            self.gfx.driver_version_comparator)
        devices = gfx.getElementsByTagName('devices')[0]
        for device, val in zip(devices.getElementsByTagName('device'),
                               self.gfx.devices.split(' ')):
            eq_(device.childNodes[0].wholeText, val)

    def test_empty_devices(self):
        self.gfx.devices = None
        self.gfx.save()
        r = self.client.get(self.fx4_url)
        self.assertNotContains(r, '<devices>')

    def test_block_id(self):
        item = (self.dom(self.fx4_url)
                .getElementsByTagName('gfxBlacklistEntry')[0])
        eq_(item.getAttribute('blockID'), 'g' + str(self.details.id))
