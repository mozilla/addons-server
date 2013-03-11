# -*- coding: utf-8 -*-
from django.conf import settings

import mock
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from files.utils import make_xpi
from zadmin import tasks


def RequestMock(response='', headers={}):
    """Mocks the request objects of urllib2 and requests modules."""
    res = mock.Mock()

    res.read.return_value = response
    res.contents = response
    res.text = response
    res.iter_content.side_effect = lambda chunk_size=1: (response,).__iter__()

    def lines():
        return [l + '\n' for l in response.split('\n')[:-1]]
    res.readlines.side_effect = lines
    res.iter_lines.side_effect = lambda: lines().__iter__()

    res.headers = headers
    res.headers['content-length'] = len(response)

    return res


def make_langpack(version):
    return make_xpi({
        'install.rdf': """<?xml version="1.0"?>

            <RDF xmlns="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                 xmlns:em="http://www.mozilla.org/2004/em-rdf#">
              <Description about="urn:mozilla:install-manifest"
                           em:id="langpack-de-DE@firefox.mozilla.org"
                           em:name="Foo Language Pack"
                           em:version="%(version)s"
                           em:type="8"
                           em:creator="mozilla.org">

                <em:targetApplication>
                  <Description>
                    <em:id>{ec8030f7-c20a-464f-9b0e-13a3a9e97384}</em:id>
                    <em:minVersion>%(version)s</em:minVersion>
                    <em:maxVersion>%(version)s.*</em:maxVersion>
                  </Description>
                </em:targetApplication>
              </Description>
            </RDF>
        """ % {'version': version}
    }).read()


class TestLangpackFetcher(amo.tests.TestCase):
    fixtures = ['base/platforms', 'zadmin/users']

    # This is the format that urllib2 returns FTP listings in.
    LISTING = ('-rw-r--r--    1 ftp      ftp        272155 Nov 19 19:54 '
               'de-DE.xpi\r\n')

    def setUp(self):
        urlopen_patch = mock.patch('zadmin.tasks.urllib2.urlopen')
        self.mock_urlopen = urlopen_patch.start()
        self.addCleanup(urlopen_patch.stop)

        request_patch = mock.patch('zadmin.tasks.requests.get')
        self.mock_request = request_patch.start()
        self.addCleanup(request_patch.stop)

    def get_langpacks(self):
        return (Addon.uncached
                     .filter(addonuser__user__email=settings.LANGPACK_OWNER_EMAIL,
                             type=amo.ADDON_LPAPP))

    def fetch_langpacks(self, version):
        self.mock_urlopen.return_value = RequestMock(self.LISTING)
        self.mock_request.return_value = RequestMock(make_langpack(version))

        tasks.fetch_langpacks(settings.LANGPACK_PATH_DEFAULT % ('firefox',
                                                                version))

    def test_fetch_new_langpack(self):
        eq_(self.get_langpacks().count(), 0)

        self.fetch_langpacks(amo.FIREFOX.latest_version)

        langpacks = self.get_langpacks()
        eq_(langpacks.count(), 1)

        a = langpacks[0]
        eq_(a.default_locale, 'de-DE')
        eq_(a.target_locale, 'de-DE')

        assert a._current_version
        eq_(a.current_version.version, amo.FIREFOX.latest_version)

        eq_(a.status, amo.STATUS_PUBLIC)
        eq_(a.current_version.files.all()[0].status,
            amo.STATUS_PUBLIC)

    def test_fetch_updated_langpack(self):
        versions = ('16.0', '17.0')

        self.fetch_langpacks(versions[0])

        eq_(self.get_langpacks().count(), 1)

        self.fetch_langpacks(versions[1])

        langpacks = self.get_langpacks()
        eq_(langpacks.count(), 1)

        a = langpacks[0]
        eq_(a.versions.count(), 2)

        v = a.versions.get(version=versions[1])
        eq_(v.files.all()[0].status, amo.STATUS_PUBLIC)

    def test_fetch_duplicate_langpack(self):
        self.fetch_langpacks(amo.FIREFOX.latest_version)

        langpacks = self.get_langpacks()
        eq_(langpacks.count(), 1)
        eq_(langpacks[0].versions.count(), 1)
        eq_(langpacks[0].versions.all()[0].version,
            amo.FIREFOX.latest_version)

        self.fetch_langpacks(amo.FIREFOX.latest_version)

        langpacks = self.get_langpacks()
        eq_(langpacks.count(), 1)
        eq_(langpacks[0].versions.count(), 1)
        eq_(langpacks[0].versions.all()[0].version,
            amo.FIREFOX.latest_version)

    def test_fetch_updated_langpack_beta(self):
        versions = ('16.0', '16.0a2')

        self.fetch_langpacks(versions[0])

        eq_(self.get_langpacks().count(), 1)

        self.fetch_langpacks(versions[1])

        langpacks = self.get_langpacks()
        eq_(langpacks.count(), 1)

        a = langpacks[0]
        eq_(a.versions.count(), 2)

        v = a.versions.get(version=versions[1])
        eq_(v.files.all()[0].status, amo.STATUS_BETA)

    def test_fetch_new_langpack_beta(self):
        self.fetch_langpacks('16.0a2')

        eq_(self.get_langpacks().count(), 0)

    def test_fetch_langpack_wrong_owner(self):
        Addon.objects.create(guid='langpack-de-DE@firefox.mozilla.org',
                             type=amo.ADDON_LPAPP)

        self.fetch_langpacks(amo.FIREFOX.latest_version)
        eq_(self.get_langpacks().count(), 0)

    def test_fetch_langpack_invalid_path_fails(self):
        self.mock_urlopen.return_value = None
        self.mock_request.return_value = None

        try:
            tasks.fetch_langpacks('../foo/')
        except ValueError, e:
            eq_(e.message, 'Invalid path')
        else:
            raise AssertionError('Invalid path accepted')
