import json

from datetime import datetime

import jinja2

from mock import Mock, patch
from pyquery import PyQuery

from olympia import amo
from olympia.addons.buttons import big_install_button, install_button
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse
from olympia.files.models import File
from olympia.versions.models import Version


class ButtonTest(TestCase):
    def setUp(self):
        super(ButtonTest, self).setUp()
        self.addon = Mock(spec=Addon)
        self.addon.is_featured.return_value = False
        self.addon.is_unreviewed.return_value = False
        self.addon.is_experimental = False
        self.addon.eula = None
        self.addon.status = amo.STATUS_PUBLIC
        self.addon.id = self.addon.pk = 42
        self.addon.slug = 'a-slug'
        self.addon.type = amo.ADDON_EXTENSION
        self.addon.privacy_policy = None

        self.version = v = Mock(spec=Version)
        self.version.id = 1337
        self.version.addon = self.addon
        v.is_compatible_by_default = False
        v.compat_override_app_versions.return_value = []
        v.is_unreviewed = False
        v.version = '2.0.3.8'
        self.addon.current_version = v

        self.file = self.get_file(amo.PLATFORM_ALL.id)
        v.all_files = [self.file]

        v.is_compatible_by_default = False
        v.compat_override_app_versions.return_value = []
        v.is_unreviewed = False

        self.platforms = amo.PLATFORM_MAC.id, amo.PLATFORM_LINUX.id
        self.platform_files = map(self.get_file, self.platforms)

        self.request = Mock()
        self.request.APP = amo.FIREFOX
        # Make GET mutable.
        self.request.GET = {}
        user = self.request.user
        user.get_and_delete_messages.__dict__['__name__'] = 'f'
        user.is_authenticated.return_value = False
        self.context = {
            'APP': amo.FIREFOX,
            'LANG': 'en-US',
            'request': self.request,
        }

    @patch('olympia.addons.buttons.render_to_string')
    def get_button(self, render_mock, **kwargs):
        """Proxy for calling install_button."""
        install_button(self.context, self.addon, **kwargs)
        # Extract button from the kwargs from the first call.
        return render_mock.call_args[0][1]['button']

    def render(self, **kwargs):
        return PyQuery(install_button(self.context, self.addon, **kwargs))

    def get_file(self, platform):
        file = File()  # Real object and not a mock to get the true methods.
        file.version = self.version
        file.pk = 666
        file.platform = platform
        file.status = amo.STATUS_PUBLIC
        file.strict_compatibility = False
        file.binary_components = False
        return file


class TestButtonSetup(ButtonTest):
    """Tests for setup code inside install_button."""

    def test_src(self):
        """src defaults to '', and can be in the context or request.GET."""
        b = self.get_button()
        assert b.src == ''

        self.request.GET['src'] = 'zz'
        b = self.get_button()
        assert b.src == 'zz'

        self.context['src'] = 'yy'
        b = self.get_button()
        assert b.src == 'yy'

        b = self.get_button(src='xx')
        assert b.src == 'xx'

    def test_collection(self):
        """Same as src; looking for collection{,_id,_uuid} in request."""
        b = self.get_button()
        assert b.collection is None

        self.request.GET['collection_uuid'] = 'aa'
        b = self.get_button()
        assert b.collection == 'aa'

        self.request.GET['collection_id'] = 'bb'
        b = self.get_button()
        assert b.collection == 'bb'

        self.request.GET['collection'] = 'cc'
        b = self.get_button()
        assert b.collection == 'cc'

        self.context['collection'] = 'dd'
        b = self.get_button()
        assert b.collection == 'dd'

        b = self.get_button(collection='ee')
        assert b.collection == 'ee'

        c = Mock()
        c.uuid = 'ff'
        b = self.get_button(collection=c)
        assert b.collection == 'ff'

    def test_version(self):
        b = self.get_button()
        assert b.version == self.version

        b = self.get_button(version=self.version)
        assert b.version == self.version


class TestButton(ButtonTest):
    """Tests for the InstallButton class."""

    def test_plain_button(self):
        b = self.get_button()
        assert b.button_class == ['download']
        assert b.install_class == []
        assert b.install_text == ''
        assert b.version == self.version
        assert b.latest
        assert not b.featured
        assert not b.unreviewed
        assert not b.show_warning

    def test_show_warning(self):
        b = self.get_button()
        assert not b.show_warning

        self.addon.is_unreviewed.return_value = True
        b = self.get_button()
        assert b.show_warning
        b = self.get_button(show_warning=False)
        assert not b.show_warning

    def test_featured(self):
        self.addon.is_featured.return_value = True
        b = self.get_button()
        assert b.featured
        assert b.button_class == ['download']
        assert b.install_class == ['featuredaddon']
        assert b.install_text == 'Featured'

    def test_unreviewed(self):
        # Throw featured in there to make sure it's ignored.
        self.addon.is_featured.return_value = True
        self.addon.is_unreviewed.return_value = True
        b = self.get_button()
        assert not b.featured
        assert b.unreviewed
        assert b.button_class == ['download', 'caution']
        assert b.install_class == ['unreviewed']
        assert b.install_text == 'Not Reviewed'

    def test_experimental(self):
        # Throw featured in there to make sure it's ignored.
        self.addon.is_featured.return_value = True
        self.addon.status = amo.STATUS_PUBLIC
        self.addon.is_experimental = True
        b = self.get_button()
        assert not b.featured
        assert b.experimental
        assert b.button_class == ['caution']
        assert b.install_class == ['lite']
        assert b.install_text == 'Experimental'

    def test_attrs(self):
        b = self.get_button()
        assert b.attrs() == {}

        self.addon.type = amo.ADDON_DICT
        b = self.get_button()
        assert b.attrs() == {'data-no-compat-necessary': 'true'}

        self.addon.type = amo.ADDON_SEARCH
        b = self.get_button()
        assert b.attrs() == {
            'data-search': 'true',
            'data-no-compat-necessary': 'true',
        }

    def test_file_details(self):
        file = self.get_file(amo.PLATFORM_ALL.id)
        self.addon.meet_the_dev_url.return_value = 'meet.dev'
        b = self.get_button()

        # Normal.
        text, url, download_url, os = b.file_details(file)
        assert text == 'Download Now'
        assert url == '/firefox/downloads/latest/a-slug/addon-42-latest'
        assert download_url == (
            '/firefox/downloads/latest/a-slug/type:attachment/addon-42-latest'
        )
        assert os is None

        # Platformer.
        file = self.get_file(amo.PLATFORM_MAC.id)
        _, _, _, os = b.file_details(file)
        assert os == amo.PLATFORM_MAC

        # Not the latest version.
        b.latest = False
        _, url, download_url, _ = b.file_details(file)
        assert url == 'http://testserver/firefox/downloads/file/666/?src='
        assert download_url == (
            'http://testserver/firefox/downloads/file/666/type:attachment/'
            '?src='
        )

    def test_file_details_unreviewed(self):
        file = self.get_file(amo.PLATFORM_ALL.id)
        file.status = amo.STATUS_AWAITING_REVIEW
        b = self.get_button()

        _, url, download_url, _ = b.file_details(file)
        assert url == 'http://testserver/firefox/downloads/file/666/?src='
        assert download_url == (
            'http://testserver/firefox/downloads/file/666/type:attachment/'
            '?src='
        )

    def test_fix_link(self):
        b = self.get_button()
        assert b.fix_link('foo.com') == 'foo.com'

        b = self.get_button(src='src')
        assert b.fix_link('foo.com') == 'foo.com?src=src'

        collection = Mock()
        collection.uuid = 'xxx'
        b = self.get_button(collection=collection)
        assert b.fix_link('foo.com') == 'foo.com?collection_id=xxx'

        b = self.get_button(collection=collection, src='src')
        self.assertUrlEqual(
            b.fix_link('foo.com'), 'foo.com?src=src&collection_id=xxx'
        )

    def test_links(self):
        self.version.all_files = self.platform_files
        links = self.get_button().links()

        assert len(links) == len(self.platforms)
        assert [x.os.id for x in links] == list(self.platforms)

    def test_link_with_invalid_file(self):
        self.version.all_files = self.platform_files
        self.version.all_files[0].status = amo.STATUS_DISABLED
        links = self.get_button().links()

        expected_platforms = self.platforms[1:]
        assert len(links) == len(expected_platforms)
        assert [x.os.id for x in links] == list(expected_platforms)

    def test_no_version(self):
        self.addon.current_version = None
        assert self.get_button().links() == []

    @patch('olympia.addons.buttons.install_button')
    @patch('olympia.addons.templatetags.jinja_helpers.statusflags')
    def test_big_install_button(self, flags_mock, install_button_mock):
        big_install_button(self.context, self.addon)
        assert install_button_mock.call_args[1] == {
            'detailed': True,
            'show_download_anyway': True,
            'size': 'prominent',
        }


class TestButtonHtml(ButtonTest):
    def test_basics(self):
        a = self.addon
        a.id = '12345'
        a.icon_url = 'icon url'
        a.meet_the_dev_url.return_value = 'meet.dev'
        a.name = 'addon name'
        self.file.hash = 'file hash'

        doc = self.render()
        assert doc('.install-shell').length == 1
        assert doc('.install').length == 1
        assert doc('.install').length == 1
        assert doc('.install-button').length == 1
        assert doc('.button').length == 1

        install = doc('.install')
        assert '12345' == install.attr('data-addon')
        assert 'icon url' == install.attr('data-icon')
        assert 'meet.dev' == install.attr('data-developers')
        assert reverse('addons.versions', args=[a.id]) == (
            install.attr('data-versions')
        )
        assert 'addon name' == install.attr('data-name')
        assert None is install.attr('data-min')
        assert None is install.attr('data-max')

        button = doc('.button')
        assert ['button', 'download'] == button.attr('class').split()
        assert 'file hash' == button.attr('data-hash')
        assert button.attr('href') == (
            '/firefox/downloads/latest/a-slug/addon-42-latest'
        )

    def test_featured(self):
        self.addon.is_featured.return_value = True
        doc = self.render()
        assert ['install', 'featuredaddon'] == (
            doc('.install').attr('class').split()
        )
        assert 'Featured' == doc('.install strong:last-child').text()

    def test_detailed_privacy_policy(self):
        policy = self.render(detailed=True)('.install-shell .privacy-policy')
        assert policy.length == 0

        self.addon.privacy_policy = 'privacy!'
        policy = self.render(detailed=True)('.install-shell .privacy-policy')
        assert policy.text() == 'View privacy policy'

    def test_experimental_detailed_warning(self):
        self.addon.status = amo.STATUS_PUBLIC
        self.addon.is_experimental = True
        warning = self.render(detailed=True)('.install-shell .warning')
        assert warning.text() == (
            'This add-on has been marked as experimental by its developers.'
        )

    def test_multi_platform(self):
        self.version.all_files = self.platform_files
        doc = self.render()
        assert doc('.button').length == 2

        for platform in self.platforms:
            os = doc(
                '.button.%s .os' % amo.PLATFORMS[platform].shortname
            ).attr('data-os')
            assert amo.PLATFORMS[platform].name == os

    def test_compatible_apps(self):
        compat = Mock()
        compat.min.version = 'min version'
        compat.max.version = 'max version'
        self.version.compatible_apps = {amo.FIREFOX: compat}
        self.version.is_compatible_by_default = True
        self.version.is_compatible_app.return_value = True
        self.version.created = datetime.now()
        install = self.render()('.install')
        assert 'min version' == install.attr('data-min')
        assert 'max version' == install.attr('data-max')

    @patch('olympia.addons.buttons.install_button')
    @patch('olympia.addons.templatetags.jinja_helpers.statusflags')
    def test_big_install_button_xss(self, flags_mock, button_mock):
        # Make sure there's no xss in statusflags.
        button_mock.return_value = jinja2.Markup('<b>button</b>')
        flags_mock.return_value = xss = '<script src="x.js">'
        s = big_install_button(self.context, self.addon)
        assert xss not in s, s

    def test_d2c_attrs(self):
        compat = Mock()
        compat.min.version = '4.0'
        compat.max.version = '12.0'
        self.version.compatible_apps = {amo.FIREFOX: compat}
        self.version.is_compatible_by_default = True
        self.version.is_compatible_app.return_value = True
        doc = self.render(impala=True)
        install_shell = doc('.install-shell')
        install = doc('.install')
        assert install
        assert install_shell
        assert install.attr('data-min') == '4.0'
        assert install.attr('data-max') == '12.0'
        assert install.attr('data-is-compatible-by-default') == 'true'
        assert install.attr('data-is-compatible-app') == 'true'
        assert install.attr('data-compat-overrides') == '[]'
        # Also test overrides.
        override = [('10.0a1', '10.*')]
        self.version.compat_override_app_versions.return_value = override
        install = self.render(impala=True)('.install')
        assert install.attr('data-is-compatible-by-default') == 'true'
        assert install.attr('data-compat-overrides') == json.dumps(override)

    def test_d2c_attrs_binary(self):
        compat = Mock()
        compat.min.version = '4.0'
        compat.max.version = '12.0'
        self.version.compatible_apps = {amo.FIREFOX: compat}
        self.version.is_compatible_by_default = False
        self.version.is_compatible_app.return_value = True
        doc = self.render(impala=True)
        install_shell = doc('.install-shell')
        install = doc('.install')
        assert install
        assert install_shell
        assert install.attr('data-min') == '4.0'
        assert install.attr('data-max') == '12.0'
        assert install.attr('data-is-compatible-by-default') == 'false'
        assert install.attr('data-is-compatible-app') == 'true'
        assert install.attr('data-compat-overrides') == '[]'

    def test_d2c_attrs_strict_and_binary(self):
        compat = Mock()
        compat.min.version = '4.0'
        compat.max.version = '12.0'
        self.version.compatible_apps = {amo.FIREFOX: compat}
        self.version.is_compatible_by_default = False
        self.version.is_compatible_app.return_value = True
        doc = self.render(impala=True)
        install_shell = doc('.install-shell')
        install = doc('.install')
        assert install
        assert install_shell
        assert install.attr('data-min') == '4.0'
        assert install.attr('data-max') == '12.0'
        assert install.attr('data-is-compatible-by-default') == 'false'
        assert install.attr('data-is-compatible-app') == 'true'
        assert install.attr('data-compat-overrides') == '[]'

    def test_show_download_anyway(self):
        compat = Mock()
        compat.min.version = '42.0'
        compat.max.version = '56.0'
        self.version.compatible_apps = {amo.FIREFOX: compat}
        self.version.is_compatible_by_default = False
        self.version.is_compatible_app.return_value = True

        doc = self.render(impala=True)
        assert not doc('.download-anyway')

        doc = self.render(impala=True, show_download_anyway=True)
        assert doc('.download-anyway')


class TestViews(TestCase):
    fixtures = ['addons/eula+contrib-addon']

    def test_eula_with_contrib_roadblock(self):
        url = reverse('addons.eula', args=[11730, 53612])
        response = self.client.get(url, follow=True)
        doc = PyQuery(response.content)
        assert doc('[data-search]').attr('class') == 'install '
