# -*- coding: utf-8 -*-
import json

from olympia import amo
from olympia.amo.tests import APITestClient, ESTestCase
from olympia.amo.urlresolvers import reverse


class TestRankingScenarios(ESTestCase):
    client_class = APITestClient

    def _check_scenario(self, query, expected, no_match=None):
        # Make sure things are properly flushed and searchable
        url = reverse('v3:addon-search')

        response = self.client.get(url, {'q': query})
        assert response.status_code == 200

        results = json.loads(response.content)['results']

        # We only check for greater or equal since we usually don't care
        # about what else ElasticSearch finds magically for any query.
        # We're mostly concerned about the first few results to check
        # our general ranking. In real-world the rest that follows matches
        # the general scoring idea.
        assert len(results) >= len(expected), (
            'Expected {} results but {} found for query "{}": {}'.format(
                len(expected), len(results), query,
                [x['name']['en-US'] for x in results]
            )
        )

        for idx, name in enumerate(expected):
            assert results[idx]['name']['en-US'] == name, (
                'Expected "{}" to be on position {} but "{}" is for query {}'
                .format(name, idx, results[idx]['name']['en-US'], query)
            )

        if no_match is not None:
            for name in no_match:
                names = [item['name']['en-US'] for item in results]
                assert name not in names, (
                    'Expected "{}" not to exist in results for query {}'
                    .format(name, query)
                )

    @classmethod
    def setUpTestData(cls):
        super(TestRankingScenarios, cls).setUpTestData()

        # This data was taken from our production add-ons to test
        # a few search scenarios. (2018-01-25)
        amo.tests.addon_factory(
            average_daily_users=18981,
            description=None,
            name='Tab Center Redux',
            slug=u'tab-center-redux',
            summary='Move your tabs to the side of your browser window.',
            weekly_downloads=915)
        amo.tests.addon_factory(
            average_daily_users=468126,
            description=None,
            name='Tab Mix Plus',
            slug=u'tab-mix-plus',
            summary=(
                'Tab Mix Plus enhances Firefox\'s tab browsing capabilities. '
                'It includes such features as duplicating tabs, controlling '
                'tab focus, tab clicking options, undo closed tabs and '
                'windows, plus much more. It also includes a full-featured '
                'session manager.'),
            weekly_downloads=3985)
        amo.tests.addon_factory(
            average_daily_users=8838,
            description=None,
            name='Redux DevTools',
            slug=u'remotedev',
            summary=(
                'DevTools for Redux with actions history, undo and replay.'),
            weekly_downloads=1032)
        amo.tests.addon_factory(
            average_daily_users=482,
            description=None,
            name='Open Image in New Tab',
            slug=u'open-image-new-tab',
            summary='Adds a context menu to open images in a new tab.',
            weekly_downloads=158)
        amo.tests.addon_factory(
            average_daily_users=2607,
            description=None,
            name='Open image in a new tab',
            slug=u'open-image-in-a-new-tab',
            summary='A context menu to open images in a new tab',
            weekly_downloads=329)
        amo.tests.addon_factory(
            average_daily_users=27832,
            description=None,
            name='Open Bookmarks in New Tab',
            slug=u'open-bookmarks-in-new-tab',
            summary=(
                'After you installed this addon to your Firefox, bookmarks '
                'are opened in new tab always.'),
            weekly_downloads=145)
        amo.tests.addon_factory(
            average_daily_users=528,
            description=None,
            name='Coinhive Blocker',
            slug=u'coinhive-blocker',
            summary='Coinhive mining blocker',
            weekly_downloads=132)
        amo.tests.addon_factory(
            average_daily_users=3015,
            description=None,
            name='CoinBlock',
            slug=u'coinblock',
            summary=(
                'With the rising popularity of coinminers in js form, this '
                'extension attempts to block those hosted on coin-hive, and '
                'cryptoloot.\nA multiple entry block list is planned.'),
            weekly_downloads=658)
        amo.tests.addon_factory(
            average_daily_users=418,
            description=None,
            name='NoMiners',
            slug=u'nominers',
            summary=(
                'NoMiners is an Add-on that tries to block cryptominers such '
                'as coinhive.\n\nBlocking those pesky miner scripts will '
                'relieve your CPU and BATTERY while browsing the web.'
                '\n\nIt\'s open source, so feel free to check out the code '
                'and submit improvements.'),
            weekly_downloads=71)
        amo.tests.addon_factory(
            average_daily_users=399485,
            description=None,
            name='Privacy Badger',
            slug=u'privacy-badger17',
            summary=(
                'Protects your privacy by blocking spying ads and invisible '
                'trackers.'),
            weekly_downloads=22931)
        amo.tests.addon_factory(
            average_daily_users=8728,
            description=None,
            name='Privacy Pass',
            slug=u'privacy-pass',
            summary=(
                'Handles passes containing cryptographically blinded tokens '
                'for bypassing challenge pages.'),
            weekly_downloads=4599)
        amo.tests.addon_factory(
            average_daily_users=15406,
            description=None,
            name='Privacy Settings',
            slug=u'privacy-settings',
            summary=(
                'Alter Firefox\'s built-in privacy settings easily with a '
                'toolbar panel.'),
            weekly_downloads=1492)
        amo.tests.addon_factory(
            average_daily_users=12857,
            description=None,
            name='Google Privacy',
            slug=u'google-privacy',
            summary=(
                'Make some popular websites respect your privacy settings.\n'
                'Please see the known issues below!'),
            weekly_downloads=117)
        amo.tests.addon_factory(
            average_daily_users=70553,
            description=None,
            name='Blur',
            slug=u'donottrackplus',
            summary='Protect your Passwords, Payments, and Privacy.',
            weekly_downloads=2224)
        amo.tests.addon_factory(
            average_daily_users=1009156,
            description=None,
            name='Ghostery',
            slug=u'ghostery',
            summary=(
                u'See who’s tracking you online and protect your privacy with '
                u'Ghostery.'),
            weekly_downloads=49315)
        amo.tests.addon_factory(
            average_daily_users=954288,
            description=None,
            name='Firebug',
            slug=u'firebug',
            summary=(
                'Firebug integrates with Firefox to put a wealth of '
                'development tools at your fingertips while you browse. You '
                'can edit, debug, and monitor CSS, HTML, and JavaScript live '
                'in any web page...'),
            weekly_downloads=21969)
        amo.tests.addon_factory(
            average_daily_users=10821,
            description=None,
            name='Firebug Autocompleter',
            slug=u'firebug-autocompleter',
            summary='Firebug command line autocomplete.',
            weekly_downloads=76)
        amo.tests.addon_factory(
            average_daily_users=11992,
            description=None,
            name='Firefinder for Firebug',
            slug=u'firefinder-for-firebug',
            summary=(
                'Finds HTML elements matching chosen CSS selector(s) or XPath '
                'expression'),
            weekly_downloads=358)
        amo.tests.addon_factory(
            average_daily_users=8200,
            description=None,
            name='Fire Drag',
            slug=u'fire-drag',
            summary='drag texts and links with/without e10s',
            weekly_downloads=506)
        amo.tests.addon_factory(
            average_daily_users=61014,
            description=None,
            name='Menu Wizard',
            slug=u's3menu-wizard',
            summary=(
                'Customizemenus=Helps removing, moving and renaming menus and '
                'menu items\nColorize important menu for ease of use! (use '
                'Style (CSS))\nChange or disable any of used keyboard '
                'shortcutsnSuppor=Firefox, Thunderbird and SeaMonkey'),
            weekly_downloads=927)
        amo.tests.addon_factory(
            average_daily_users=81237,
            description=None,
            name='Add-ons Manager Context Menu',
            slug=u'am-context',
            summary='Add more items to Add-ons Manager context menu.',
            weekly_downloads=169)
        amo.tests.addon_factory(
            average_daily_users=51,
            description=None,
            name='Frame Demolition',
            slug=u'frame-demolition',
            summary=(
                'Enabling route to load abstracted file layer in select '
                'sites.'),
            weekly_downloads=70)
        amo.tests.addon_factory(
            average_daily_users=99,
            description=None,
            name='reStyle',
            slug=u're-style',
            summary=(
                'A user style manager which can load local files and apply UI '
                'styles even in Firefox 57+'),
            weekly_downloads=70)
        amo.tests.addon_factory(
            average_daily_users=150,
            description=None,
            name='MegaUpload DownloadHelper',
            slug=u'megaupload-downloadhelper',
            summary=(
                'Download from MegaUpload.\nMegaUpload Download Helper will '
                'start your download once ready.\nMegaUpload Download Helper '
                'will monitor time limitations and will auto-start your '
                'download.'),
            weekly_downloads=77)
        amo.tests.addon_factory(
            average_daily_users=2830,
            description=None,
            name='RapidShare DownloadHelper',
            slug=u'rapidshare-downloadhelper',
            summary=(
                'Note from Mozilla: This add-on has been discontinued. Try '
                '<a rel="nofollow" href="https://addons.mozilla.org/firefox/'
                'addon/rapidshare-helper/">Rapidshare Helper</a> instead.\n\n'
                'RapidShare Download Helper will start your download once '
                'ready.'),
            weekly_downloads=125)
        amo.tests.addon_factory(
            average_daily_users=98716,
            description=None,
            name='Popup Blocker',
            slug=u'popup_blocker',
            summary=(
                'Prevents your web browser from opening a new window on top '
                'of the content or web site you are viewing. The Addon also '
                'supresses unwanted advertisement windows on your screen. '
                'The one deciding what consitutes a popup is the user.'),
            weekly_downloads=3940)
        amo.tests.addon_factory(
            average_daily_users=8830,
            description=None,
            name='No Flash',
            slug=u'no-flash',
            summary=(
                'Replace Youtube, Vimeo and Dailymotion Flash video players '
                'embedded on third-party website by the HTML5 counterpart '
                'when the content author still use the old style embed '
                '(Flash).\n\nSource code at <a rel="nofollow" href="https://'
                'outgoing.prod.mozaws.net/v1/14b404a3c05779fa94b24e0bffc0d710'
                '6836f1d6b771367b065fb96e9c8656b9/https%3A//github.com/hfigui'
                'ere/no-flash">https://github.com/hfiguiere/no-flash</a>'),
            weekly_downloads=77)
        amo.tests.addon_factory(
            average_daily_users=547880,
            description=None,
            name='Download Flash and Video',
            slug=u'download-flash-and-video',
            summary=(
                'Download Flash and Video is a great download helper tool '
                'that lets you download Flash games and Flash videos '
                '(YouTube, Facebook, Dailymotion, Google Videos and more) '
                'with a single click.\nThe downloader is very easy to use.'),
            weekly_downloads=65891)
        amo.tests.addon_factory(
            average_daily_users=158796,
            description=None,
            name='YouTube Flash Video Player',
            slug=u'youtube-flash-video-player',
            summary=(
                'YouTube Flash Video Player is a powerful tool that will let '
                'you choose Flash video player as default YouTube video '
                'player.'),
            weekly_downloads=12239)
        amo.tests.addon_factory(
            average_daily_users=206980,
            description=None,
            name='YouTube Flash Player',
            slug=u'youtube-flash-player',
            summary=(
                u'A very lightweight add-on that allows you to watch YouTube™ '
                u'videos using Flash® Player instead of the '
                u'default HTML5 player. The Flash® Player will consume less '
                u'CPU and RAM resources if your device doesn\'t easily '
                u'support HTML5 videos. Try it!'),
            weekly_downloads=21882)
        amo.tests.addon_factory(
            average_daily_users=5056, description=None,
            name='Disable Hello, Pocket & Reader+',
            slug=u'disable-hello-pocket-reader',
            summary=(
                'Turn off Pocket, Reader, Hello and WebRTC bloatware - keep '
                'browser fast and clean'),
            weekly_downloads=85)
        amo.tests.addon_factory(
            average_daily_users=26135,
            description=None,
            name='Reader',
            slug=u'reader',
            summary='Reader is the ultimate Reader tool for Firefox.',
            weekly_downloads=2463)
        amo.tests.addon_factory(
            average_daily_users=53412,
            description=None,
            name='Disable WebRTC',
            slug=u'happy-bonobo-disable-webrtc',
            summary=(
                'WebRTC leaks your actual IP addresses from behind your VPN, '
                'by default.'),
            weekly_downloads=10583)
        amo.tests.addon_factory(
            average_daily_users=12953,
            description=None,
            name='In My Pocket',
            slug=u'in-my-pocket',
            summary=(
                'For all those who are missing the old Firefox Pocket addon, '
                'and not satisfied with the new Pocket integration, here is '
                'an unofficial client for the excellent Pocket service. '
                'Hope you\'ll enjoy it!'),
            weekly_downloads=1123)
        amo.tests.addon_factory(
            name='GrApple Yummy')
        amo.tests.addon_factory(
            name='Delicious Bookmarks')

        # Some more or less Dummy data to test a few very specific scenarios
        # e.g for exact name matching
        amo.tests.addon_factory(
            name='Merge Windows', type=amo.ADDON_EXTENSION,
            average_daily_users=0, weekly_downloads=0),
        amo.tests.addon_factory(
            name='Merge All Windows', type=amo.ADDON_EXTENSION,
            average_daily_users=0, weekly_downloads=0),
        amo.tests.addon_factory(
            name='All Downloader Professional', type=amo.ADDON_EXTENSION,
            average_daily_users=0, weekly_downloads=0),

        amo.tests.addon_factory(
            name='test addon test11', type=amo.ADDON_EXTENSION,
            average_daily_users=0, weekly_downloads=0),
        amo.tests.addon_factory(
            name='test addon test21', type=amo.ADDON_EXTENSION,
            average_daily_users=0, weekly_downloads=0),
        amo.tests.addon_factory(
            name='test addon test31', type=amo.ADDON_EXTENSION,
            average_daily_users=0, weekly_downloads=0),

        amo.tests.addon_factory(
            name='1-Click YouTube Video Download',
            type=amo.ADDON_EXTENSION,
            average_daily_users=566337, weekly_downloads=150000,
            description=(
                'button, click that button, 1-Click Youtube Video '
                'Downloader is a click click great tool')),
        amo.tests.addon_factory(
            name='Amazon 1-Click Lock', type=amo.ADDON_EXTENSION,
            average_daily_users=50, weekly_downloads=0),

        cls.refresh()

    def test_scenario_tab_center_redux(self):
        self._check_scenario('tab center redux', (
            'Tab Center Redux',
            'Tab Mix Plus',
            'Redux DevTools',
        ))

    def test_scenario_open_image_new_tab(self):
        # TODO, should not put the "a new tab" thing first :-/
        self._check_scenario('Open Image in New Tab', (
            'Open image in a new tab',
            'Open Image in New Tab',
        ))

    def test_scenario_coinhive(self):
        # TODO, should match "CoinBlock"
        self._check_scenario('CoinHive', (
            'Coinhive Blocker',
            'NoMiners',  # via description
            # 'CoinBlock',  # via prefix search
        ))

    def test_scenario_privacy(self):
        self._check_scenario('Privacy', (
            'Privacy Badger',
            'Privacy Settings',
            'Google Privacy',  # More users, summary
            'Privacy Pass',
            'Ghostery',  # Crazy amount of users, summary
            'Blur',  # summary + many users but not as many as ghostery
        ))

    def test_scenario_firebu(self):
        self._check_scenario('firebu', (
            'Firebug',
            # unclear why preference to Firebug Autocompleter,
            # weekly downloads + users?
            'Firefinder for Firebug',
            'Firebug Autocompleter',
            'Fire Drag',
        ))

    def test_scenario_fireb(self):
        self._check_scenario('fireb', (
            'Firebug',
            'Firefinder for Firebug',
            'Firebug Autocompleter',
            'Fire Drag',
        ))

    def test_scenario_menu_wizzard(self):
        self._check_scenario('Menu Wizzard', (
            'Menu Wizard',  # (fuzzy, typo)
            'Add-ons Manager Context Menu',  # partial match + users
        ))

    def test_scenario_frame_demolition(self):
        self._check_scenario('Frame Demolition', (
            'Frame Demolition',
        ))

    def test_scenario_demolition(self):
        # Find "Frame Demolition" via a typo
        self._check_scenario('Demolation', (
            'Frame Demolition',
        ))

    def test_scenario_restyle(self):
        self._check_scenario('reStyle', (
            'reStyle',
        ))

    def test_scenario_megaupload_downloadhelper(self):
        # Doesn't find "RapidShare DownloadHelper" anymore
        # since we now query by "MegaUpload AND DownloadHelper"
        self._check_scenario('MegaUpload DownloadHelper', (
            'MegaUpload DownloadHelper',
        ))

    def test_scenario_downloadhelper(self):
        # No direct match, "Download Flash and Video" has
        # huge amount of users that puts it first here
        self._check_scenario('DownloadHelper', (
            'Download Flash and Video',
            '1-Click YouTube Video Download',
            'RapidShare DownloadHelper',
            'MegaUpload DownloadHelper',
        ))

    def test_scenario_megaupload(self):
        self._check_scenario('MegaUpload', (
            # TODO: I have litterally NO idea :-/
            'Popup Blocker',
            'MegaUpload DownloadHelper',
        ))

    def test_scenario_no_flash(self):
        # TODO: Doesn't put "No Flash" on first line, does the "No"
        # do something special here?
        self._check_scenario('No Flash', (
            'Download Flash and Video',
            'YouTube Flash Player',
            'YouTube Flash Video Player',
            'No Flash'
        ))

    def test_scenario_disable_hello_pocket_reader_plus(self):
        self._check_scenario('Disable Hello, Pocket & Reader+', (
            'Disable Hello, Pocket & Reader+',  # yeay!
        ))

    def test_scenario_grapple(self):
        """Making sure this scenario works via the API,

        see `legacy_api.SearchTest` for various examples.
        """
        self._check_scenario('grapple', (
            'GrApple Yummy',
        ))

    def test_scenario_delicious(self):
        """Making sure this scenario works via the API,

        see `legacy_api.SearchTest` for various examples.
        """
        self._check_scenario('delicious', (
            'Delicious Bookmarks',
        ))

    def test_score_boost_name_match(self):
        # Tests that we match directly "Merge Windows" and also find
        # "Merge All Windows" because of slop=1
        self._check_scenario('merge windows', (
            'Merge Windows',
            'Merge All Windows',
        ), no_match=(
            'All Downloader Professional',
        ))

        self._check_scenario('merge all windows', (
            'Merge All Windows',
            'Merge Windows',
            'All Downloader Professional',
        ))

    def test_score_boost_exact_match(self):
        """Test that we rank exact matches at the top."""
        self._check_scenario('test addon test21', (
            'test addon test21',
        ))

    def test_score_boost_exact_match_description_hijack(self):
        """Test that we rank exact matches at the top."""
        self._check_scenario('Amazon 1-Click Lock', (
            'Amazon 1-Click Lock',
            '1-Click YouTube Video Download',
        ))
