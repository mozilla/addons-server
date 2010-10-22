import jingo
from mock import patch, Mock, sentinel
from nose.tools import eq_
from pyquery import PyQuery
import test_utils

import amo
import amo.models
from amo.urlresolvers import reverse
from addons.buttons import install_button


def setup():
    jingo.load_helpers()


class ButtonTest(test_utils.TestCase):

    def setUp(self):
        self.addon = Mock()
        self.addon.is_featured.return_value = False
        self.addon.is_category_featured.return_value = False
        self.addon.is_unreviewed.return_value = False
        self.addon.has_eula = False
        self.addon.status = amo.STATUS_PUBLIC
        self.addon.id = 2
        self.addon.type = amo.ADDON_EXTENSION

        self.version = v = Mock()
        v.is_unreviewed = False
        v.is_beta = False
        v.version = 'v1'
        self.addon.current_version = v

        self.file = self.get_file(amo.PLATFORM_ALL)
        v.all_files = [self.file]

        self.platforms = amo.PLATFORM_MAC, amo.PLATFORM_LINUX
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

    @patch('addons.buttons.jingo.env.get_template')
    def get_button(self, t_mock, **kwargs):
        """Proxy for calling install_button."""
        template_mock = Mock()
        t_mock.return_value = template_mock
        install_button(self.context, self.addon, **kwargs)
        # Extract button from the kwargs from the first call.
        return template_mock.render.call_args[1]['button']

    def render(self, **kwargs):
        return PyQuery(install_button(self.context, self.addon, **kwargs))

    def get_file(self, platform):
        file = Mock()
        file.platform_id = platform.id
        file.latest_xpi_url.return_value = 'xpi.latest'
        file.get_url_path.return_value = 'xpi.url'
        file.eula_url.return_value = 'eula.url'
        file.status = amo.STATUS_PUBLIC
        return file


class TestButtonSetup(ButtonTest):
    """Tests for setup code inside install_button."""

    def test_eula(self):
        """show_eula defaults to true, can be overridden in request.GET."""
        self.addon.has_eula = True
        b = self.get_button()
        assert b.show_eula

        b = self.get_button(show_eula=False)
        assert not b.show_eula

        self.request.GET['eula'] = ''
        b = self.get_button()
        assert not b.show_eula

        self.request.GET['eula'] = 'xx'
        b = self.get_button(show_eula=False)
        assert b.show_eula

        self.setUp()
        self.addon.has_eula = False
        b = self.get_button()
        assert not b.show_eula

    def test_eula_and_contrib(self):
        """If show_eula is True, show_contrib should be off."""
        self.addon.has_eula = True
        self.addon.annoying = amo.CONTRIB_ROADBLOCK
        b = self.get_button(show_eula=False)
        assert not b.show_eula
        assert b.show_contrib

    def test_src(self):
        """src defaults to '', and can be in the context or request.GET."""
        b = self.get_button()
        eq_(b.src, '')

        self.request.GET['src'] = 'zz'
        b = self.get_button()
        eq_(b.src, 'zz')

        self.context['src'] = 'yy'
        b = self.get_button()
        eq_(b.src, 'yy')

        b = self.get_button(src='xx')
        eq_(b.src, 'xx')

    def test_collection(self):
        """Same as src; looking for collection{,_id,_uuid} in request."""
        b = self.get_button()
        eq_(b.collection, None)

        self.request.GET['collection_uuid'] = 'aa'
        b = self.get_button()
        eq_(b.collection, 'aa')

        self.request.GET['collection_id'] = 'bb'
        b = self.get_button()
        eq_(b.collection, 'bb')

        self.request.GET['collection'] = 'cc'
        b = self.get_button()
        eq_(b.collection, 'cc')

        self.context['collection'] = 'dd'
        b = self.get_button()
        eq_(b.collection, 'dd')

        b = self.get_button(collection='ee')
        eq_(b.collection, 'ee')

        c = Mock()
        c.uuid = 'ff'
        b = self.get_button(collection=c)
        eq_(b.collection, 'ff')


class TestButton(ButtonTest):
    """Tests for the InstallButton class."""

    def test_plain_button(self):
        b = self.get_button()
        eq_(b.button_class, ['download'])
        eq_(b.install_class, [])
        eq_(b.install_text, '')
        eq_(b.version, self.version)
        assert b.latest
        assert not b.featured
        assert not b.unreviewed
        assert not b.self_hosted
        assert not b.show_eula
        assert not b.show_contrib
        assert not b.show_warning

    def test_show_contrib(self):
        b = self.get_button()
        assert not b.show_contrib

        self.addon.takes_contributions = True
        b = self.get_button()
        assert not b.show_contrib

        self.addon.annoying = amo.CONTRIB_ROADBLOCK
        b = self.get_button()
        assert b.show_contrib
        eq_(b.button_class, ['contrib', 'go'])
        eq_(b.install_class, ['contrib'])

    def test_show_warning(self):
        b = self.get_button()
        assert not b.show_warning

        self.addon.is_unreviewed.return_value = True
        b = self.get_button()
        assert b.show_warning
        b = self.get_button(show_warning=False)
        assert not b.show_warning

        self.setUp()
        self.addon.status = amo.STATUS_LISTED
        b = self.get_button()
        assert b.show_warning

    def test_eula(self):
        self.addon.has_eula = True
        b = self.get_button()
        eq_(b.button_class, ['eula', 'go'])
        eq_(b.install_class, ['eula'])

    def test_accept_eula(self):
        self.addon.has_eula = True
        b = self.get_button(show_eula=False)
        assert 'accept' in b.install_class

        file = self.get_file(amo.PLATFORM_ALL)
        text, _, _ = b.file_details(file)
        eq_(text, 'Accept and Download')

    def test_featured(self):
        self.addon.is_featured.return_value = True
        b = self.get_button()
        assert b.featured
        eq_(b.button_class, ['download'])
        eq_(b.install_class, ['featuredaddon'])
        eq_(b.install_text, 'Featured')

    def test_category_featured(self):
        self.addon.is_category_featured.return_value = True
        b = self.get_button()
        assert b.featured

    def test_unreviewed(self):
        # Throw featured in there to make sure it's ignored.
        self.addon.is_featured.return_value = True
        self.addon.is_unreviewed.return_value = True
        b = self.get_button()
        assert not b.featured
        assert b.unreviewed
        eq_(b.button_class, ['download', 'caution'])
        eq_(b.install_class, ['unreviewed'])
        eq_(b.install_text, 'Not Reviewed')

    def test_beta(self):
        # Throw featured in there to make sure it's ignored.
        self.addon.is_featured.return_value = True
        self.version.is_beta = True
        b = self.get_button()
        assert not b.featured
        assert b.is_beta
        eq_(b.button_class, ['download', 'caution'])
        eq_(b.install_class, ['unreviewed', 'beta'])
        eq_(b.install_text, 'Not Reviewed')

    def test_self_hosted(self):
        # Throw featured in there to make sure it's ignored.
        self.addon.is_featured.return_value = True
        self.addon.homepage = sentinel.url
        self.addon.status = amo.STATUS_LISTED

        b = self.get_button()
        assert not b.featured
        assert b.self_hosted
        eq_(b.button_class, ['go'])
        eq_(b.install_class, ['selfhosted'])
        eq_(b.install_text, 'Self Hosted')

        links = b.links()
        eq_(len(links), 1)
        eq_(links[0].url, sentinel.url)

    def test_attrs(self):
        b = self.get_button()
        eq_(b.attrs(), {})

        self.addon.takes_contributions = True
        self.addon.annoying = amo.CONTRIB_AFTER
        self.addon.type = amo.ADDON_SEARCH

        b = self.get_button()
        eq_(b.attrs(), {'data-after': 'contrib', 'data-search': 'true'})

    def test_file_details(self):
        file = self.get_file(amo.PLATFORM_ALL)
        self.addon.meet_the_dev_url.return_value = 'meet.dev'
        b = self.get_button()

        # Normal.
        text, url, os = b.file_details(file)
        eq_(text, 'Download Now')
        eq_(url, 'xpi.latest')
        eq_(os, None)

        # Platformer.
        file = self.get_file(amo.PLATFORM_MAC)
        _, _, os = b.file_details(file)
        eq_(os, amo.PLATFORM_MAC)

        # Not the latest version.
        b.latest = False
        _, url, _ = b.file_details(file)
        eq_(url, 'xpi.url')

        # EULA roadblock.
        b.show_eula = True
        text, url, _ = b.file_details(file)
        eq_(text, 'Continue to Download&nbsp;&rarr;')
        eq_(url, 'eula.url')

        # Contribution roadblock.
        b.show_eula = False
        b.show_contrib = True
        text, url, _ = b.file_details(file)
        eq_(text, 'Continue to Download&nbsp;&rarr;')
        eq_(url,
            '/en-US/firefox/addon/2/contribute/roadblock/?eula=&version=v1')

    def test_file_details_unreviewed(self):
        file = self.get_file(amo.PLATFORM_ALL)
        file.status = amo.STATUS_UNREVIEWED
        b = self.get_button()

        _, url, _ = b.file_details(file)
        eq_(url, 'xpi.url')

    def test_fix_link(self):
        b = self.get_button()
        eq_(b.fix_link('foo.com'), 'foo.com')

        b = self.get_button(src='src')
        eq_(b.fix_link('foo.com'), 'foo.com?src=src')

        collection = Mock()
        collection.uuid = 'xxx'
        b = self.get_button(collection=collection)
        eq_(b.fix_link('foo.com'), 'foo.com?collection=xxx')

        b = self.get_button(collection=collection, src='src')
        eq_(b.fix_link('foo.com'), 'foo.com?src=src&collection=xxx')

    def test_links(self):
        self.version.all_files = self.platform_files
        links = self.get_button().links()

        eq_(len(links), len(self.platforms))
        eq_([x.os for x in links], list(self.platforms))

    def test_link_with_invalid_file(self):
        self.version.all_files = self.platform_files
        self.version.all_files[0].status = amo.STATUS_DISABLED
        links = self.get_button().links()

        expected_platforms = self.platforms[1:]
        eq_(len(links), len(expected_platforms))
        eq_([x.os for x in links], list(expected_platforms))

    def test_no_version(self):
        self.addon.current_version = None
        eq_(self.get_button().links(), [])


class TestButtonHtml(ButtonTest):

    def test_basics(self):
        a = self.addon
        a.id = 'addon id'
        a.icon_url = 'icon url'
        a.meet_the_dev_url.return_value = 'meet.dev'
        a.name = 'addon name'
        self.file.hash = 'file hash'

        doc = self.render()
        eq_(doc('.install-shell').length, 1)
        eq_(doc('.install').length, 1)
        eq_(doc('.install').length, 1)
        eq_(doc('.install-button').length, 1)
        eq_(doc('.button').length, 1)

        install = doc('.install')
        eq_('addon id', install.attr('data-addon'))
        eq_('icon url', install.attr('data-icon'))
        eq_('meet.dev', install.attr('data-developers'))
        eq_('addon name', install.attr('data-name'))
        eq_(None, install.attr('data-min'))
        eq_(None, install.attr('data-max'))

        button = doc('.button')
        eq_(['button', 'download'], button.attr('class').split())
        eq_('file hash', button.attr('data-hash'))
        eq_('xpi.latest', button.attr('href'))

    def test_featured(self):
        self.addon.is_featured.return_value = True
        doc = self.render()
        eq_(['install', 'featuredaddon'],
            doc('.install').attr('class').split())
        eq_('Featured', doc('.install strong:last-child').text())

    def test_unreviewed(self):
        self.addon.status = amo.STATUS_UNREVIEWED
        self.addon.is_unreviewed.return_value = True
        self.addon.get_url_path.return_value = 'addon.url'
        button = self.render()('.button.caution')
        eq_('addon.url', button.attr('href'))
        eq_('xpi.url', button.attr('data-realurl'))

    def test_multi_platform(self):
        self.version.all_files = self.platform_files
        doc = self.render()
        eq_(doc('.button').length, 2)

        for platform in self.platforms:
            os = doc('.button.%s .os' % platform.shortname).attr('data-os')
            eq_(platform.name, os)

    def test_compatible_apps(self):
        compat = Mock()
        compat.min.version = 'min version'
        compat.max.version = 'max version'
        self.version.compatible_apps = {amo.FIREFOX: compat}
        install = self.render()('.install')
        eq_('min version', install.attr('data-min'))
        eq_('max version', install.attr('data-max'))

    def test_caching(self):
        """Make sure we don't cache too hard and ignore flags."""
        self.addon.has_eula = True
        doc = self.render()
        assert doc('.button').hasClass('eula')

        doc = self.render(show_eula=False)
        assert not doc('.button').hasClass('eula')

    def test_platformer_with_eula(self):
        """Don't show platform text for eula buttons."""
        self.version.all_files = self.platform_files
        self.addon.has_eula = True
        doc = self.render()
        eq_(doc('.eula .os').text(), '')

    def test_contrib_text_with_platform(self):
        self.version.all_files = self.platform_files
        self.addon.takes_contributions = True
        self.addon.annoying = amo.CONTRIB_ROADBLOCK
        self.addon.meet_the_dev_url.return_value = 'addon.url'
        doc = self.render()
        eq_(doc('.contrib .os').text(), '')


class TestViews(test_utils.TestCase):
    fixtures = ['addons/eula+contrib-addon', 'base/apps']

    def test_eula_with_contrib_roadblock(self):
        url = reverse('addons.eula', args=[11730, 53612])
        response = self.client.get(url, follow=True)
        doc = PyQuery(response.content)
        eq_(doc('[data-search]').attr('class'), 'install accept')
