# -*- coding: utf-8 -*-
import urlparse

from django.conf import settings

import mock

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.applications.models import AppVersion
from olympia.files.utils import make_xpi
from olympia.versions.compare import version_int
from olympia.versions.models import License
from olympia.zadmin import tasks


def RequestMock(response='', headers=None):
    """Mocks the request objects of urllib2 and requests modules."""
    res = mock.Mock()

    res.read.return_value = response
    res.contents = response
    res.text = response
    res.iter_lines.side_effect = lambda chunk_size=1: (response.split('\n')
                                                               .__iter__())
    res.iter_content.side_effect = lambda chunk_size=1: (response,).__iter__()

    def lines():
        return [l + '\n' for l in response.split('\n')[:-1]]
    res.readlines.side_effect = lines
    res.iter_lines.side_effect = lambda: lines().__iter__()

    res.headers = headers or {}
    res.headers['content-length'] = len(response)

    return res


def make_langpack(version):
    versions = (version, '%s.*' % version)

    for version in versions:
        AppVersion.objects.get_or_create(application=amo.FIREFOX.id,
                                         version=version,
                                         version_int=version_int(version))

    return make_xpi({
        'install.rdf': """<?xml version="1.0"?>

            <RDF xmlns="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                 xmlns:em="http://www.mozilla.org/2004/em-rdf#">
              <Description about="urn:mozilla:install-manifest"
                           em:id="langpack-de-DE@firefox.mozilla.org"
                           em:name="Foo Language Pack"
                           em:version="{0}"
                           em:type="8"
                           em:creator="mozilla.org">

                <em:targetApplication>
                  <Description>
                    <em:id>{{ec8030f7-c20a-464f-9b0e-13a3a9e97384}}</em:id>
                    <em:minVersion>{0}</em:minVersion>
                    <em:maxVersion>{1}</em:maxVersion>
                  </Description>
                </em:targetApplication>
              </Description>
            </RDF>
        """.format(*versions)
    }).read()


class TestLangpackFetcher(TestCase):
    fixtures = ['zadmin/users']

    LISTING = 'pretend-this-is-a-sha256-sum  win32/xpi/de-DE.xpi\n'

    def setUp(self):
        super(TestLangpackFetcher, self).setUp()
        request_patch = mock.patch('olympia.zadmin.tasks.requests.get')
        self.mock_request = request_patch.start()
        self.addCleanup(request_patch.stop)
        License.objects.create(name=u'MPL', builtin=1)

    def get_langpacks(self):
        return (Addon.objects.no_cache()
                .filter(addonuser__user__email=settings.LANGPACK_OWNER_EMAIL,
                        type=amo.ADDON_LPAPP))

    def fetch_langpacks(self, version):
        path = settings.LANGPACK_PATH_DEFAULT % ('firefox', version)

        base_url = urlparse.urljoin(settings.LANGPACK_DOWNLOAD_BASE, path)
        list_url = urlparse.urljoin(base_url, settings.LANGPACK_MANIFEST_PATH)
        langpack_url = urlparse.urljoin(base_url, 'de-DE.xpi')

        responses = {list_url: RequestMock(self.LISTING),
                     langpack_url: RequestMock(make_langpack(version))}

        self.mock_request.reset_mock()
        self.mock_request.side_effect = lambda url, **kw: responses.get(url)

        tasks.fetch_langpacks(path)

        self.mock_request.assert_has_calls(
            [mock.call(list_url, verify=settings.CA_CERT_BUNDLE_PATH),
             mock.call(langpack_url, verify=settings.CA_CERT_BUNDLE_PATH)])

    @mock.patch('olympia.zadmin.tasks.sign_file')
    def test_fetch_new_langpack(self, mock_sign_file):
        assert self.get_langpacks().count() == 0

        self.fetch_langpacks(amo.FIREFOX.latest_version)

        langpacks = self.get_langpacks()
        assert langpacks.count() == 1

        addon = langpacks[0]
        assert addon.default_locale == 'de-DE'
        assert addon.target_locale == 'de-DE'
        assert addon.summary == addon.name

        assert addon._current_version
        assert addon.current_version.version == amo.FIREFOX.latest_version

        file_ = addon.current_version.files.get()

        # has_complete_metadata checks license and categories were set.
        assert addon.has_complete_metadata(), addon.get_required_metadata()
        assert file_.status == amo.STATUS_PUBLIC
        assert addon.status == amo.STATUS_PUBLIC

        # Make sure it has strict compatibility enabled (should be done
        # automatically for legacy extensions, that includes langpacks)
        assert file_.strict_compatibility is True

        mock_sign_file.assert_called_once_with(file_)

    @mock.patch('olympia.zadmin.tasks.sign_file')
    def test_fetch_updated_langpack(self, mock_sign_file):
        versions = ('16.0', '17.0')

        self.fetch_langpacks(versions[0])

        assert self.get_langpacks().count() == 1

        self.fetch_langpacks(versions[1])

        langpacks = self.get_langpacks()
        assert langpacks.count() == 1

        addon = langpacks[0]
        assert addon.versions.count() == 2
        assert addon.summary == addon.name

        # has_complete_metadata checks license and categories were set.
        assert addon.has_complete_metadata(), addon.get_required_metadata()
        version = addon.versions.get(version=versions[1])
        assert addon.current_version == version
        file_ = version.files.get()
        assert file_.status == amo.STATUS_PUBLIC

        # Make sure it has strict compatibility enabled (should be done
        # automatically for legacy extensions, that includes langpacks)
        assert file_.strict_compatibility is True

        mock_sign_file.assert_called_with(file_)

    @mock.patch('olympia.zadmin.tasks.sign_file')
    def test_fetch_duplicate_langpack(self, mock_sign_file):
        self.fetch_langpacks(amo.FIREFOX.latest_version)

        langpacks = self.get_langpacks()
        assert langpacks.count() == 1
        assert langpacks[0].versions.count() == 1
        assert (langpacks[0].versions.all()[0].version ==
                amo.FIREFOX.latest_version)

        self.fetch_langpacks(amo.FIREFOX.latest_version)

        langpacks = self.get_langpacks()
        assert langpacks.count() == 1
        addon = langpacks[0]
        assert addon.versions.count() == 1
        assert (addon.versions.all()[0].version ==
                amo.FIREFOX.latest_version)

        mock_sign_file.assert_called_once_with(
            addon.current_version.files.get())

    @mock.patch('olympia.zadmin.tasks.sign_file')
    def test_fetch_langpack_wrong_owner(self, mock_sign_file):
        Addon.objects.create(guid='langpack-de-DE@firefox.mozilla.org',
                             type=amo.ADDON_LPAPP)

        self.fetch_langpacks(amo.FIREFOX.latest_version)
        assert self.get_langpacks().count() == 0

        assert not mock_sign_file.called

    @mock.patch('olympia.zadmin.tasks.sign_file')
    def test_fetch_langpack_invalid_path_fails(self, mock_sign_file):
        self.mock_request.return_value = None

        with self.assertRaises(ValueError) as exc:
            tasks.fetch_langpacks('../foo/')
        assert str(exc.exception) == 'Invalid path'

        assert not mock_sign_file.called

    @mock.patch('olympia.zadmin.tasks.sign_file')
    def test_fetch_new_langpack_name_summary_separate(self, mock_sign_file):
        """Test for https://github.com/mozilla/addons-server/issues/5432"""
        assert self.get_langpacks().count() == 0

        self.fetch_langpacks(amo.FIREFOX.latest_version)

        langpacks = self.get_langpacks()
        assert langpacks.count() == 1

        addon = langpacks[0]
        assert addon.default_locale == 'de-DE'
        assert addon.target_locale == 'de-DE'
        assert str(addon.summary) == str(addon.name)

        # The string is the same but we don't use the same
        # translation instance
        assert addon.summary.id != addon.name.id

        assert addon._current_version
        assert addon.current_version.version == amo.FIREFOX.latest_version
