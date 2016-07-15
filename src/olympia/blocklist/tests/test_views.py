# -*- coding: utf-8 -*-
import base64
import json
from datetime import datetime
from time import sleep
from xml.dom import minidom

from django.conf import settings
from django.core.cache import cache

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse
from olympia.blocklist.models import (
    BlocklistApp, BlocklistCA, BlocklistDetail, BlocklistGfx, BlocklistItem,
    BlocklistIssuerCert, BlocklistPlugin, BlocklistPref)
from olympia.blocklist.utils import JSON_DATE_FORMAT

base_xml = """
<?xml version="1.0"?>
<blocklist xmlns="http://www.mozilla.org/2006/addons-blocklist">
</blocklist>
"""


class XMLAssertsMixin(object):

    def assertOptional(self, obj, field, xml_field):
        """Make sure that if the field isn't filled in, it's not in the XML."""
        # Save the initial value.
        initial = getattr(obj, field)
        try:
            # If not set, the field isn't in the XML.
            obj.update(**{field: ''})
            assert self.dom(self.fx4_url).getElementsByTagName(xml_field) == []
            # If set, it's in the XML.
            obj.update(**{field: 'foobar'})
            element = self.dom(self.fx4_url).getElementsByTagName(xml_field)[0]
            assert element.firstChild.nodeValue == 'foobar'
        finally:
            obj.update(**{field: initial})

    def assertAttribute(self, obj, field, tag, attr_name):
        # Save the initial value.
        initial = getattr(obj, field)
        try:
            # If set, it's in the XML.
            obj.update(**{field: 'foobar'})
            element = self.dom(self.fx4_url).getElementsByTagName(tag)[0]
            assert element.getAttribute(attr_name) == 'foobar'
        finally:
            obj.update(**{field: initial})

    def assertEscaped(self, obj, field):
        """Make sure that the field content is XML escaped."""
        obj.update(**{field: 'http://example.com/?foo=<bar>&baz=crux'})
        r = self.client.get(self.fx4_url)
        assert 'http://example.com/?foo=&lt;bar&gt;&amp;baz=crux' in r.content


class BlocklistViewTest(TestCase):

    def setUp(self):
        super(BlocklistViewTest, self).setUp()
        self.fx4_url = reverse('blocklist', args=[3, amo.FIREFOX.guid, '4.0'])
        self.fx2_url = reverse('blocklist', args=[2, amo.FIREFOX.guid, '2.0'])
        self.tb4_url = reverse('blocklist', args=[3, amo.THUNDERBIRD.guid,
                                                  '4.0'])
        self.mobile_url = reverse('blocklist', args=[2, amo.MOBILE.guid, '.9'])
        cache.clear()
        self.json_url = reverse('blocklist.json')
        self.details = BlocklistDetail.objects.create(
            name='blocked item',
            who='All Firefox and Fennec users',
            why='Security issue',
            bug='http://bug.url.com/',
        )

    def create_blplugin(self, app_guid=None, app_min=None, app_max=None,
                        *args, **kw):
        plugin = BlocklistPlugin.objects.create(*args, **kw)
        app = BlocklistApp.objects.create(blplugin=plugin, guid=app_guid,
                                          min=app_min, max=app_max)
        return plugin, app

    def normalize(self, s):
        return '\n'.join(x.strip() for x in s.split())

    def eq_(self, x, y):
        assert self.normalize(x) == self.normalize(y)

    def dom(self, url):
        r = self.client.get(url)
        return minidom.parseString(r.content)


class BlocklistItemTest(XMLAssertsMixin, BlocklistViewTest):

    def setUp(self):
        super(BlocklistItemTest, self).setUp()
        self.item = BlocklistItem.objects.create(guid='guid@addon.com',
                                                 details=self.details)
        self.pref = BlocklistPref.objects.create(blitem=self.item,
                                                 pref='foo.bar')
        self.app = BlocklistApp.objects.create(blitem=self.item,
                                               guid=amo.FIREFOX.guid)

    def stupid_unicode_test(self):
        junk = u'\xc2\x80\x15\xc2\x80\xc3'
        url = reverse('blocklist', args=[3, amo.FIREFOX.guid, junk])
        # Just make sure it doesn't fail.
        assert self.client.get(url).status_code == 200

    def test_content_type(self):
        response = self.client.get(self.fx4_url)
        assert response['Content-Type'] == 'text/xml'

    def test_empty_string_goes_null_on_save(self):
        b = BlocklistItem(guid='guid', min='', max='', os='')
        b.save()
        assert b.min is None
        assert b.max is None
        assert b.os is None

    def test_lastupdate(self):
        def eq(a, b):
            assert a == b.replace(microsecond=0)

        def find_lastupdate():
            bl = self.dom(self.fx4_url).getElementsByTagName('blocklist')[0]
            t = int(bl.getAttribute('lastupdate')) / 1000
            return datetime.fromtimestamp(t)

        eq(find_lastupdate(), self.item.created)

        self.item.save()
        eq(find_lastupdate(), self.item.modified)

        plugin, app = self.create_blplugin(app_guid=amo.FIREFOX.guid)
        eq(find_lastupdate(), plugin.created)
        plugin.save()
        eq(find_lastupdate(), plugin.modified)

        gfx = BlocklistGfx.objects.create(guid=amo.FIREFOX.guid)
        eq(find_lastupdate(), gfx.created)
        gfx.save()
        eq(find_lastupdate(), gfx.modified)

        assert (self.item.created != self.item.modified != plugin.created !=
                plugin.modified != gfx.created != gfx.modified)

    def test_no_items(self):
        self.item.delete()
        dom = self.dom(self.fx4_url)
        children = dom.getElementsByTagName('blocklist')[0].childNodes
        # There are only text nodes.
        assert all(e.nodeType == 3 for e in children)

    def test_existing_user_cookie(self):
        self.client.cookies[settings.BLOCKLIST_COOKIE] = 'adfadf'
        self.client.get(self.fx4_url)
        assert self.client.cookies[settings.BLOCKLIST_COOKIE].value == 'adfadf'

    def test_url_params(self):
        assert self.client.get(self.fx4_url).status_code == 200
        assert self.client.get(self.fx2_url).status_code == 200
        # We ignore trailing url parameters.
        assert self.client.get(self.fx4_url + 'other/junk/').status_code == 200

    def test_app_guid(self):
        # There's one item for Firefox.
        r = self.client.get(self.fx4_url)
        assert r.status_code == 200
        assert len(r.context['items']) == 1

        # There are no items for mobile.
        r = self.client.get(self.mobile_url)
        assert r.status_code == 200
        assert len(r.context['items']) == 0

        # Without the app constraint we see the item.
        self.app.delete()
        r = self.client.get(self.mobile_url)
        assert r.status_code == 200
        assert len(r.context['items']) == 1

    def test_item_guid(self):
        items = self.dom(self.fx4_url).getElementsByTagName('emItem')
        assert len(items) == 1
        assert items[0].getAttribute('id') == 'guid@addon.com'

    def test_block_id(self):
        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        assert item.getAttribute('blockID') == 'i' + str(self.details.id)

    def test_block_id_consistency(self):
        # Clean the current blocklist so that we have only one
        self.item.delete()

        same_guid = 'guid-conflict@addon.com'

        # Create a first detail
        first_created_details = BlocklistDetail.objects.create(
            name='blocked item',
            who='All Firefox and Fennec users',
            why='Security issue',
            bug='http://bug.url.com/4567',
        )
        # Create a second detail
        secondly_created_details = BlocklistDetail.objects.create(
            name='blocked item',
            who='All Firefox and Fennec users',
            why='Security issue',
            bug='http://bug.url.com/1234',
        )
        # Create a first item with the greatest blockID
        BlocklistItem.objects.create(
            guid=same_guid,
            details=first_created_details
        )
        sleep(1)
        # Create a second item with the lowest blockID
        BlocklistItem.objects.create(
            guid=same_guid,
            details=secondly_created_details
        )

        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        assert item.getAttribute('id') == same_guid

        # Check that the blockID is the smallest
        assert item.getAttribute('blockID') == (
            'i%s' % str(first_created_details.id))

    def test_item_os(self):
        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        assert 'os' not in item.attributes.keys()

        self.item.update(os='win,mac')
        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        assert item.getAttribute('os') == 'win,mac'

    def test_item_pref(self):
        self.item.update(severity=2)
        assert len(self.vr()) == 1
        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        prefs = item.getElementsByTagName('prefs')
        pref = prefs[0].getElementsByTagName('pref')
        assert pref[0].firstChild.nodeValue == self.pref.pref

    def test_item_severity(self):
        self.item.update(severity=2)
        assert len(self.vr()) == 1
        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        vrange = item.getElementsByTagName('versionRange')
        assert vrange[0].getAttribute('severity') == '2'

    def test_item_severity_zero(self):
        # Don't show severity if severity==0.
        self.item.update(severity=0, min='0.1')
        assert len(self.vr()) == 1
        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        vrange = item.getElementsByTagName('versionRange')
        assert vrange[0].getAttribute('minVersion') == '0.1'
        assert not vrange[0].hasAttribute('severity')

    def vr(self):
        item = self.dom(self.fx4_url).getElementsByTagName('emItem')[0]
        return item.getElementsByTagName('versionRange')

    def test_item_version_range(self):
        self.item.update(min='0.1')
        assert len(self.vr()) == 1
        assert self.vr()[0].attributes.keys() == ['minVersion']
        assert self.vr()[0].getAttribute('minVersion') == '0.1'

        self.item.update(max='0.2')
        keys = self.vr()[0].attributes.keys()
        assert len(keys) == 2
        assert 'minVersion' in keys
        assert 'maxVersion' in keys
        assert self.vr()[0].getAttribute('minVersion') == '0.1'
        assert self.vr()[0].getAttribute('maxVersion') == '0.2'

    def test_item_multiple_version_range(self):
        # There should be two <versionRange>s under one <emItem>.
        self.item.update(min='0.1', max='0.2')
        BlocklistItem.objects.create(guid=self.item.guid, severity=3)

        item = self.dom(self.fx4_url).getElementsByTagName('emItem')
        assert len(item) == 1
        vr = item[0].getElementsByTagName('versionRange')
        assert len(vr) == 2
        assert vr[0].getAttribute('minVersion') == '0.1'
        assert vr[0].getAttribute('maxVersion') == '0.2'
        assert vr[1].getAttribute('severity') == '3'

    def test_item_target_app(self):
        app = self.app
        self.app.delete()
        self.item.update(severity=2)
        version_range = self.vr()[0]
        assert version_range.getElementsByTagName('targetApplication') == []

        app.save()
        version_range = self.vr()[0]
        target_app = version_range.getElementsByTagName('targetApplication')
        assert len(target_app) == 1
        assert target_app[0].getAttribute('id') == amo.FIREFOX.guid

        app.update(min='0.1', max='*')
        version_range = self.vr()[0]
        target_app = version_range.getElementsByTagName('targetApplication')
        assert target_app[0].getAttribute('id') == amo.FIREFOX.guid
        tvr = target_app[0].getElementsByTagName('versionRange')
        assert tvr[0].getAttribute('minVersion') == '0.1'
        assert tvr[0].getAttribute('maxVersion') == '*'

    def test_item_multiple_apps(self):
        # Make sure all <targetApplication>s go under the same <versionRange>.
        self.app.update(min='0.1', max='0.2')
        BlocklistApp.objects.create(guid=amo.FIREFOX.guid, blitem=self.item,
                                    min='3.0', max='3.1')
        version_range = self.vr()[0]
        apps = version_range.getElementsByTagName('targetApplication')
        assert len(apps) == 2
        assert apps[0].getAttribute('id') == amo.FIREFOX.guid
        vr = apps[0].getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('minVersion') == '0.1'
        assert vr.getAttribute('maxVersion') == '0.2'
        assert apps[1].getAttribute('id') == amo.FIREFOX.guid
        vr = apps[1].getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('minVersion') == '3.0'
        assert vr.getAttribute('maxVersion') == '3.1'

    def test_item_empty_version_range(self):
        # No version_range without an app, min, max, or severity.
        self.app.delete()
        self.item.update(min=None, max=None, severity=None)
        assert len(self.vr()) == 0

    def test_item_empty_target_app(self):
        # No empty <targetApplication>.
        self.item.update(severity=1)
        self.app.delete()
        app = self.dom(self.fx4_url).getElementsByTagName('targetApplication')
        assert app == []

    def test_item_target_empty_version_range(self):
        app = self.dom(self.fx4_url).getElementsByTagName('targetApplication')
        assert app[0].getElementsByTagName('versionRange') == []

    def test_name(self):
        self.assertAttribute(self.item, field='name', tag='emItem',
                             attr_name='name')

    def test_creator(self):
        self.assertAttribute(self.item, field='creator', tag='emItem',
                             attr_name='creator')

    def test_homepage_url(self):
        self.assertAttribute(self.item, field='homepage_url', tag='emItem',
                             attr_name='homepageURL')

    def test_update_url(self):
        self.assertAttribute(self.item, field='update_url', tag='emItem',
                             attr_name='updateURL')

    def test_urls_escaped(self):
        self.assertEscaped(self.item, 'homepage_url')
        self.assertEscaped(self.item, 'update_url')

    def test_addons_json(self):
        self.item.update(os='WINNT 5.0', name='addons name',
                         severity=0, min='0', max='*')

        self.app.update(min='2.0', max='3.0')

        app2 = BlocklistApp.objects.create(
            blitem=self.item, guid=amo.FIREFOX.guid,
            min='1.0', max='2.0')

        r = self.client.get(self.json_url)
        blocklist = json.loads(r.content)

        item = blocklist['addons'][0]

        assert item['guid'] == self.item.guid
        assert item['name'] == self.item.name
        assert item['os'] == self.item.os

        # VersionRange
        assert item['versionRange'] == [{
            'severity': 0,
            'minVersion': '0',
            'maxVersion': '*',
            'targetApplication': [{
                'guid': self.app.guid,
                'minVersion': '2.0',
                'maxVersion': '3.0',
            }, {
                'guid': app2.guid,
                'minVersion': '1.0',
                'maxVersion': '2.0',
            }]
        }]

        created = self.item.details.created
        assert item['details'] == {
            'name': 'blocked item',
            'who': 'All Firefox and Fennec users',
            'why': 'Security issue',
            'created': created.strftime(JSON_DATE_FORMAT),
            'bug': 'http://bug.url.com/'
        }

    def test_addons_json_with_no_app(self):
        self.item.update(os='WINNT 5.0',
                         severity=0, min='0', max='*')

        self.app.delete()

        r = self.client.get(self.json_url)
        blocklist = json.loads(r.content)

        item = blocklist['addons'][0]

        assert 'name' not in item
        assert item['os'] == self.item.os

        # VersionRange
        assert item['versionRange'] == [{
            'severity': 0,
            'minVersion': '0',
            'maxVersion': '*',
            'targetApplication': []
        }]

        created = self.item.details.created
        assert item['details'] == {
            'name': 'blocked item',
            'who': 'All Firefox and Fennec users',
            'why': 'Security issue',
            'created': created.strftime(JSON_DATE_FORMAT),
            'bug': 'http://bug.url.com/'
        }

    def test_two_blitem_for_same_addon_json(self):
        self.item.update(os='WINNT 5.0', name='addons name',
                         severity=0, min='0', max='*')

        BlocklistApp.objects.create(blitem=self.item, guid=amo.FIREFOX.guid,
                                    min='1.0', max='2.0')

        details = BlocklistDetail.objects.create(
            name='blocked item',
            who='All Thunderbird users',
            why='Security issue',
            bug='http://bug.url.com/',
        )

        item2 = BlocklistItem.objects.create(guid=self.item.guid,
                                             os='WINNT 5.0',
                                             name='addons name',
                                             severity=0, min='0', max='*',
                                             details=details)

        BlocklistApp.objects.create(blitem=item2,
                                    guid=amo.THUNDERBIRD.guid,
                                    min='17.0', max='*')

        r = self.client.get(self.json_url)
        blocklist = json.loads(r.content)

        assert 'Firefox' in r.content
        assert 'Thunderbird' in r.content
        # Items are not grouped by guid
        assert len(blocklist['addons']) == 2
        assert len(blocklist['addons'][0]['versionRange']) == 1
        assert len(blocklist['addons'][1]['versionRange']) == 1


class BlocklistPluginTest(XMLAssertsMixin, BlocklistViewTest):

    def setUp(self):
        super(BlocklistPluginTest, self).setUp()
        self.plugin, self.app = self.create_blplugin(app_guid=amo.FIREFOX.guid,
                                                     details=self.details)

    def test_no_plugins(self):
        dom = BlocklistViewTest.dom(self, self.mobile_url)
        children = dom.getElementsByTagName('blocklist')[0].childNodes
        # There are only text nodes.
        assert all(e.nodeType == 3 for e in children)

    def dom(self, url=None):
        url = url or self.fx4_url
        r = self.client.get(url)
        d = minidom.parseString(r.content)
        return d.getElementsByTagName('pluginItem')[0]

    def test_plugin_empty(self):
        self.app.delete()
        assert self.dom().attributes.keys() == ['blockID']
        assert self.dom().getElementsByTagName('match') == []
        assert self.dom().getElementsByTagName('versionRange') == []

    def test_block_id(self):
        item = self.dom(self.fx4_url)
        assert item.getAttribute('blockID') == 'p' + str(self.details.id)

    def test_plugin_os(self):
        self.plugin.update(os='win')
        assert sorted(self.dom().attributes.keys()) == ['blockID', 'os']
        assert self.dom().getAttribute('os') == 'win'

    def test_plugin_xpcomabi(self):
        self.plugin.update(xpcomabi='win')
        assert sorted(self.dom().attributes.keys()) == ['blockID', 'xpcomabi']
        assert self.dom().getAttribute('xpcomabi') == 'win'

    def test_plugin_name(self):
        self.plugin.update(name='flash')
        match = self.dom().getElementsByTagName('match')
        assert len(match) == 1
        assert dict(match[0].attributes.items()) == (
            {'name': 'name', 'exp': 'flash'})

    def test_plugin_description(self):
        self.plugin.update(description='flash')
        match = self.dom().getElementsByTagName('match')
        assert len(match) == 1
        assert dict(match[0].attributes.items()) == (
            {'name': 'description', 'exp': 'flash'})

    def test_plugin_filename(self):
        self.plugin.update(filename='flash')
        match = self.dom().getElementsByTagName('match')
        assert len(match) == 1
        assert dict(match[0].attributes.items()) == (
            {'name': 'filename', 'exp': 'flash'})

    def test_plugin_severity(self):
        self.plugin.update(severity=2)
        v = self.dom().getElementsByTagName('versionRange')[0]
        assert v.getAttribute('severity') == '2'

    def test_plugin_severity_zero(self):
        self.plugin.update(severity=0)
        v = self.dom().getElementsByTagName('versionRange')[0]
        assert v.getAttribute('severity') == '0'

    def test_plugin_no_target_app(self):
        self.plugin.update(severity=1, min='1', max='2')
        self.app.delete()
        vr = self.dom().getElementsByTagName('versionRange')[0]
        # There should not be a <targetApplication> if there was no app.
        assert vr.getElementsByTagName('targetApplication') == []
        assert vr.getAttribute('severity') == '1'
        assert vr.getAttribute('minVersion') == '1'
        assert vr.getAttribute('maxVersion') == '2'

    def test_plugin_with_target_app(self):
        self.plugin.update(severity=1)
        self.app.update(guid=amo.FIREFOX.guid, min='1', max='2')
        vr = self.dom().getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('severity') == '1'
        assert not vr.getAttribute('vulnerabilitystatus')

        app = vr.getElementsByTagName('targetApplication')[0]
        assert app.getAttribute('id') == amo.FIREFOX.guid

        vr = app.getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('minVersion') == '1'
        assert vr.getAttribute('maxVersion') == '2'

    def test_plugin_with_multiple_target_apps(self):
        self.plugin.update(severity=1, min='5', max='6')
        self.app.update(guid=amo.FIREFOX.guid, min='1', max='2')
        BlocklistApp.objects.create(guid=amo.THUNDERBIRD.guid,
                                    min='3', max='4',
                                    blplugin=self.plugin)
        vr = self.dom().getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('severity') == '1'
        assert vr.getAttribute('minVersion') == '5'
        assert vr.getAttribute('maxVersion') == '6'
        assert not vr.getAttribute('vulnerabilitystatus')

        app = vr.getElementsByTagName('targetApplication')[0]
        assert app.getAttribute('id') == amo.FIREFOX.guid

        vr = app.getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('minVersion') == '1'
        assert vr.getAttribute('maxVersion') == '2'

        vr = self.dom(self.tb4_url).getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('severity') == '1'
        assert vr.getAttribute('minVersion') == '5'
        assert vr.getAttribute('maxVersion') == '6'
        assert not vr.getAttribute('vulnerabilitystatus')

        app = vr.getElementsByTagName('targetApplication')[0]
        assert app.getAttribute('id') == amo.THUNDERBIRD.guid

        vr = app.getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('minVersion') == '3'
        assert vr.getAttribute('maxVersion') == '4'

    def test_plugin_with_target_app_with_vulnerability(self):
        self.plugin.update(severity=0, vulnerability_status=2)
        self.app.update(guid=amo.FIREFOX.guid, min='1', max='2')
        vr = self.dom().getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('severity') == '0'
        assert vr.getAttribute('vulnerabilitystatus') == '2'

        app = vr.getElementsByTagName('targetApplication')[0]
        assert app.getAttribute('id') == amo.FIREFOX.guid

        vr = app.getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('minVersion') == '1'
        assert vr.getAttribute('maxVersion') == '2'

    def test_plugin_with_severity_only(self):
        self.plugin.update(severity=1)
        self.app.delete()
        vr = self.dom().getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('severity') == '1'
        assert not vr.getAttribute('vulnerabilitystatus')
        assert vr.getAttribute('minVersion') == ''
        assert vr.getAttribute('maxVersion') == ''
        # There should not be a <targetApplication> if there was no app
        assert vr.getElementsByTagName('targetApplication') == []

    def test_plugin_without_severity_and_with_vulnerability(self):
        self.plugin.update(severity=0, vulnerability_status=1)
        self.app.delete()
        vr = self.dom().getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('severity') == '0'
        assert vr.getAttribute('vulnerabilitystatus') == '1'
        assert vr.getAttribute('minVersion') == ''
        assert vr.getAttribute('maxVersion') == ''

    def test_plugin_without_severity_and_with_vulnerability_and_minmax(self):
        self.plugin.update(severity=0, vulnerability_status=1, min='2.0',
                           max='3.0')
        self.app.delete()
        vr = self.dom().getElementsByTagName('versionRange')[0]
        assert vr.getAttribute('severity') == '0'
        assert vr.getAttribute('vulnerabilitystatus') == '1'
        assert vr.getAttribute('minVersion') == '2.0'
        assert vr.getAttribute('maxVersion') == '3.0'

    def test_plugin_apiver_lt_3(self):
        self.plugin.update(severity='2')
        # No min & max so the app matches.
        e = self.dom(self.fx2_url).getElementsByTagName('versionRange')[0]
        assert e.getAttribute('severity') == '2'
        assert e.getElementsByTagName('targetApplication') == []

        # The app version is not in range.
        self.app.update(min='3.0', max='4.0')
        self.assertRaises(IndexError, self.dom, self.fx2_url)

        # The app is back in range.
        self.app.update(min='1.1')
        e = self.dom(self.fx2_url).getElementsByTagName('versionRange')[0]
        assert e.getAttribute('severity') == '2'
        assert e.getElementsByTagName('targetApplication') == []

    def test_info_url(self):
        self.assertOptional(self.plugin, 'info_url', 'infoURL')
        self.assertEscaped(self.plugin, 'info_url')

    def test_plugins_json(self):
        self.plugin.update(os='WINNT 5.0',
                           xpcomabi='win',
                           name='plugin name',
                           description='plugin description',
                           filename='plugin filename',
                           info_url='http://info.url.com/', severity=0,
                           vulnerability_status=1, min='2.0', max='3.0')

        self.app.update(min='2.0', max='3.0')

        r = self.client.get(self.json_url)
        blocklist = json.loads(r.content)

        plugin = blocklist['plugins'][0]

        # Add infoURL
        assert plugin['infoURL'] == self.plugin.info_url
        assert plugin['name'] == self.plugin.name
        assert plugin['os'] == self.plugin.os
        assert plugin['xpcomabi'] == self.plugin.xpcomabi
        assert plugin['matchName'] == self.plugin.name
        assert plugin['matchFilename'] == self.plugin.filename
        assert plugin['matchDescription'] == self.plugin.description

        # VersionRange
        assert plugin['versionRange'] == [{
            'severity': 0,
            'vulnerabilityStatus': 1,
            'minVersion': '2.0',
            'maxVersion': '3.0',
            'targetApplication': [{
                'guid': self.app.guid,
                'minVersion': '2.0',
                'maxVersion': '3.0',
            }]
        }]

        created = self.plugin.details.created
        assert plugin['details'] == {
            'name': 'blocked item',
            'who': 'All Firefox and Fennec users',
            'why': 'Security issue',
            'created': created.strftime(JSON_DATE_FORMAT),
            'bug': 'http://bug.url.com/'
        }

    def test_plugins_json_with_no_app(self):
        self.plugin.update(os='WINNT 5.0',
                           xpcomabi='win',
                           name='plugin name',
                           description='plugin description',
                           filename='plugin filename',
                           info_url='http://info.url.com/', severity=0,
                           vulnerability_status=1, min='2.0', max='3.0')

        self.app.delete()

        r = self.client.get(self.json_url)
        blocklist = json.loads(r.content)

        plugin = blocklist['plugins'][0]

        # Add infoURL
        assert plugin['infoURL'] == self.plugin.info_url
        assert plugin['name'] == self.plugin.name
        assert plugin['os'] == self.plugin.os
        assert plugin['xpcomabi'] == self.plugin.xpcomabi
        assert plugin['matchName'] == self.plugin.name
        assert plugin['matchFilename'] == self.plugin.filename
        assert plugin['matchDescription'] == self.plugin.description

        # VersionRange
        assert plugin['versionRange'] == [{
            'severity': 0,
            'vulnerabilityStatus': 1,
            'minVersion': '2.0',
            'maxVersion': '3.0',
            'targetApplication': []
        }]

        created = self.plugin.details.created
        assert plugin['details'] == {
            'name': 'blocked item',
            'who': 'All Firefox and Fennec users',
            'why': 'Security issue',
            'created': created.strftime(JSON_DATE_FORMAT),
            'bug': 'http://bug.url.com/'
        }

    def test_plugins_json_with_multiple_apps(self):
        self.plugin.update(os='WINNT 5.0',
                           xpcomabi='win',
                           name='plugin name',
                           description='plugin description',
                           filename='plugin filename',
                           info_url='http://info.url.com/', severity=0,
                           vulnerability_status=1, min='2.0', max='3.0')

        self.app.update(min='2.0', max='3.0')

        BlocklistApp.objects.create(guid=amo.THUNDERBIRD.guid,
                                    min='3', max='4',
                                    blplugin=self.plugin)

        r = self.client.get(self.json_url)
        blocklist = json.loads(r.content)

        plugin = blocklist['plugins'][0]

        # Add infoURL
        assert plugin['infoURL'] == self.plugin.info_url
        assert plugin['name'] == self.plugin.name
        assert plugin['os'] == self.plugin.os
        assert plugin['xpcomabi'] == self.plugin.xpcomabi
        assert plugin['matchName'] == self.plugin.name
        assert plugin['matchFilename'] == self.plugin.filename
        assert plugin['matchDescription'] == self.plugin.description

        # VersionRange
        assert plugin['versionRange'] == [{
            'severity': 0,
            'vulnerabilityStatus': 1,
            'minVersion': '2.0',
            'maxVersion': '3.0',
            'targetApplication': [{
                'guid': self.app.guid,
                'minVersion': '2.0',
                'maxVersion': '3.0',
            }, {
                'guid': amo.THUNDERBIRD.guid,
                'minVersion': '3',
                'maxVersion': '4',
            }]
        }]

        created = self.plugin.details.created
        assert plugin['details'] == {
            'name': 'blocked item',
            'who': 'All Firefox and Fennec users',
            'why': 'Security issue',
            'created': created.strftime(JSON_DATE_FORMAT),
            'bug': 'http://bug.url.com/'
        }


class BlocklistGfxTest(BlocklistViewTest):

    def setUp(self):
        super(BlocklistGfxTest, self).setUp()
        self.gfx = BlocklistGfx.objects.create(
            guid=amo.FIREFOX.guid, os='os', vendor='vendor', devices='x y z',
            feature='feature', feature_status='status', details=self.details,
            driver_version='version', driver_version_max='version max',
            driver_version_comparator='compare', hardware='giant_robot',
            application_min='4.0', application_max='38.*')

    def test_no_gfx(self):
        dom = self.dom(self.mobile_url)
        children = dom.getElementsByTagName('blocklist')[0].childNodes
        # There are only text nodes.
        assert all(e.nodeType == 3 for e in children)

    def test_gfx(self):
        r = self.client.get(self.fx4_url)
        dom = minidom.parseString(r.content)
        gfx = dom.getElementsByTagName('gfxBlacklistEntry')[0]

        def find(e):
            return gfx.getElementsByTagName(e)[0].childNodes[0].wholeText

        assert find('os') == self.gfx.os
        assert find('feature') == self.gfx.feature
        assert find('vendor') == self.gfx.vendor
        assert find('featureStatus') == self.gfx.feature_status
        assert find('driverVersion') == self.gfx.driver_version
        assert find('driverVersionMax') == self.gfx.driver_version_max
        expected_version_comparator = self.gfx.driver_version_comparator
        assert find('driverVersionComparator') == expected_version_comparator
        assert find('hardware') == self.gfx.hardware
        devices = gfx.getElementsByTagName('devices')[0]
        for device, val in zip(devices.getElementsByTagName('device'),
                               self.gfx.devices.split(' ')):
            assert device.childNodes[0].wholeText == val

    def test_gfx_versionrange(self):
        self.gfx.update(application_min='4.0', application_max='38.0')

        def get_range():
            r = self.client.get(self.fx4_url)
            dom = minidom.parseString(r.content)
            gfx = dom.getElementsByTagName('gfxBlacklistEntry')[0]

            return gfx.getElementsByTagName('versionRange')[0]

        range = get_range()
        assert range.getAttribute('minVersion') == '4.0'
        assert range.getAttribute('maxVersion') == '38.0'

        self.gfx.update(application_min='4.0', application_max=None)

        range = get_range()
        assert range.getAttribute('minVersion') == '4.0'
        assert range.getAttribute('maxVersion') == ''

        self.gfx.update(application_min=None, application_max='38.0')

        range = get_range()
        assert range.getAttribute('minVersion') == ''
        assert range.getAttribute('maxVersion') == '38.0'

    def test_empty_devices(self):
        self.gfx.devices = None
        self.gfx.save()
        r = self.client.get(self.fx4_url)
        self.assertNotContains(r, '<devices>')

    def test_no_empty_nodes(self):
        self.gfx.update(
            os=None, vendor=None, devices=None, feature=None,
            feature_status=None, driver_version=None, driver_version_max=None,
            driver_version_comparator=None, hardware=None,
            application_min=None, application_max=None)
        r = self.client.get(self.fx4_url)
        self.assertNotContains(r, '<os>')
        self.assertNotContains(r, '<vendor>')
        self.assertNotContains(r, '<devices>')
        self.assertNotContains(r, '<feature>')
        self.assertNotContains(r, '<featureStatus>')
        self.assertNotContains(r, '<driverVersion>')
        self.assertNotContains(r, '<driverVersionMax>')
        self.assertNotContains(r, '<driverVersionComparator>')
        self.assertNotContains(r, '<hardware>')
        self.assertNotContains(r, '<versionRange>')

    def test_block_id(self):
        item = (self.dom(self.fx4_url)
                .getElementsByTagName('gfxBlacklistEntry')[0])
        assert item.getAttribute('blockID') == 'g' + str(self.details.id)

    def test_gfx_json(self):
        r = self.client.get(self.json_url)
        blocklist = json.loads(r.content)

        gfx_item = blocklist['gfx'][0]

        assert gfx_item.get('blockID') == self.gfx.block_id
        assert gfx_item.get('os') == self.gfx.os
        assert gfx_item.get('feature') == self.gfx.feature
        assert gfx_item.get('vendor') == self.gfx.vendor
        assert gfx_item.get('featureStatus') == self.gfx.feature_status
        assert gfx_item.get('driverVersion') == self.gfx.driver_version
        assert gfx_item.get('driverVersionMax') == self.gfx.driver_version_max
        expected_comparator = self.gfx.driver_version_comparator
        assert gfx_item.get('driverVersionComparator') == expected_comparator
        assert gfx_item.get('hardware') == self.gfx.hardware
        devices = gfx_item.get('devices')
        assert devices == self.gfx.devices.split(' ')
        created = self.gfx.details.created
        assert gfx_item['details'] == {
            'name': 'blocked item',
            'who': 'All Firefox and Fennec users',
            'why': 'Security issue',
            'created': created.strftime(JSON_DATE_FORMAT),
            'bug': 'http://bug.url.com/'
        }
        assert gfx_item['versionRange'] == {
            'minVersion': '4.0',
            'maxVersion': '38.*'
        }

    def test_gfx_no_devices_json(self):
        self.gfx.devices = None
        self.gfx.save()
        r = self.client.get(self.json_url)
        blocklist = json.loads(r.content)
        gfx_item = blocklist['gfx'][0]
        assert gfx_item['devices'] == []

    def test_gfx_no_null_values_json(self):
        self.gfx.update(os=None, vendor=None, devices=None,
                        feature=None, feature_status=None,
                        driver_version=None, driver_version_max=None,
                        driver_version_comparator=None, hardware=None,
                        application_min=None, application_max=None)
        r = self.client.get(self.json_url)
        blocklist = json.loads(r.content)
        gfx_item = blocklist['gfx'][0]
        assert 'os' not in gfx_item
        assert 'vendor' not in gfx_item
        assert 'feature' not in gfx_item
        assert 'featureStatus' not in gfx_item
        assert 'driverVersion' not in gfx_item
        assert 'driverVersionMax' not in gfx_item
        assert 'driverVersionComparator' not in gfx_item
        assert 'hardware' not in gfx_item
        assert 'versionRange' not in gfx_item


class BlocklistCATest(BlocklistViewTest):

    def setUp(self):
        super(BlocklistCATest, self).setUp()
        self.ca = BlocklistCA.objects.create(data=u'Ètå…, ≥•≤')

    def test_ca(self):
        r = self.client.get(self.fx4_url)
        dom = minidom.parseString(r.content)
        ca = dom.getElementsByTagName('caBlocklistEntry')[0]
        assert base64.b64decode(ca.childNodes[0].toxml()) == 'Ètå…, ≥•≤'

    def test_ca_json(self):
        r = self.client.get(self.json_url)
        blocklist = json.loads(r.content)
        ca = blocklist['ca']
        assert base64.b64decode(ca) == 'Ètå…, ≥•≤'


class BlocklistIssuerCertTest(BlocklistViewTest):

    def setUp(self):
        super(BlocklistIssuerCertTest, self).setUp()
        self.issuerCertBlock = BlocklistIssuerCert.objects.create(
            issuer='testissuer', serial='testserial',
            details=BlocklistDetail.objects.create(
                name='one', who='Who', why='Why', bug='http://bug.url.com/'))
        self.issuerCertBlock2 = BlocklistIssuerCert.objects.create(
            issuer='anothertestissuer', serial='anothertestserial',
            details=BlocklistDetail.objects.create(
                name='two', who='Who', why='Why', bug='http://bug.url.com/'))

    def test_extant_nodes(self):
        r = self.client.get(self.fx4_url)
        dom = minidom.parseString(r.content)

        certItem = dom.getElementsByTagName('certItem')[0]
        assert certItem.getAttribute('issuerName') == (
            self.issuerCertBlock.issuer)
        serialNode = dom.getElementsByTagName('serialNumber')[0]
        serialNumber = serialNode.childNodes[0].wholeText
        assert serialNumber == self.issuerCertBlock.serial

        certItem = dom.getElementsByTagName('certItem')[1]
        assert certItem.getAttribute('issuerName') == (
            self.issuerCertBlock2.issuer)
        serialNode = dom.getElementsByTagName('serialNumber')[1]
        serialNumber = serialNode.childNodes[0].wholeText
        assert serialNumber == self.issuerCertBlock2.serial

    def test_certs_json(self):
        r = self.client.get(self.json_url)
        blocklist = json.loads(r.content)

        certItem = blocklist['certificates'][0]
        assert certItem['blockID'] == self.issuerCertBlock.block_id
        assert certItem['issuerName'] == self.issuerCertBlock.issuer
        assert certItem['serialNumber'] == self.issuerCertBlock.serial
        created = self.issuerCertBlock.details.created
        assert certItem['details'] == {
            'name': 'one',
            'who': 'Who',
            'why': 'Why',
            'created': created.strftime(JSON_DATE_FORMAT),
            'bug': 'http://bug.url.com/'
        }

        certItem = blocklist['certificates'][1]
        assert certItem['blockID'] == self.issuerCertBlock2.block_id
        assert certItem['issuerName'] == self.issuerCertBlock2.issuer
        assert certItem['serialNumber'] == self.issuerCertBlock2.serial
        created = self.issuerCertBlock2.details.created
        assert certItem['details'] == {
            'name': 'two',
            'who': 'Who',
            'why': 'Why',
            'created': created.strftime(JSON_DATE_FORMAT),
            'bug': 'http://bug.url.com/'
        }

    def test_json_url_is_not_prefixed_and_does_not_redirect(self):
        assert self.json_url == '/blocked/blocklists.json'
        r = self.client.get(self.json_url, follow=False)
        assert r.status_code == 200
