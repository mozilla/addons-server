# -*- coding: utf-8 -*-
import json

from django.conf import settings
from django.utils.encoding import force_text

from olympia import amo
from olympia.amo.tests import APITestClient, ESTestCase, reverse_ns
from olympia.constants.promoted import LINE, RECOMMENDED, VERIFIED
from olympia.constants.search import SEARCH_LANGUAGE_TO_ANALYZER


class TestRankingScenarios(ESTestCase):
    client_class = APITestClient

    def _check_scenario(self, query, expected, **kwargs):
        def get_name_from_result(item, expected_lang):
            name = item['name'].get(expected_lang)
            if name is None:
                name = item['name'].get(item['default_locale'], '??????')
            return name

        # Use v5 version to ensure we get objects for translations all the
        # time. We don't necessarily specify the language in all tests, but we
        # want objects all the time for simplicity.
        url = reverse_ns('addon-search', api_version='v5')
        params = {'lang': 'en-US'}
        expected_lang = kwargs.pop('expected_lang', None)
        params.update(kwargs)
        params['q'] = query
        response = self.client.get(url, params)
        assert response.status_code == 200
        data = json.loads(force_text(response.content))
        assert data['count']
        results = data['results']

        if expected_lang is None:
            expected_lang = params['lang']

        assert len(results) == len(
            expected
        ), 'Expected {} results but {} found for query "{}": {}'.format(
            len(expected),
            len(results),
            query,
            [x['name'][expected_lang] for x in results],
        )

        for idx, addon in enumerate(expected):
            expected_name = addon[0]
            expected_score = addon[1]
            found_name = get_name_from_result(results[idx], expected_lang)
            found_score = results[idx]['_score']

            assert found_name == expected_name, (
                'Expected "{}" to be on position {} with score {} but '
                '"{}" was found instead with score {} for query {}'.format(
                    expected_name, idx, expected_score, found_name, found_score, query
                )
            )

            # Quick and dirty way to generate a script to change the expected
            # scores in this file, uncomment this block then launch the script
            # it generates (note that it will skip the assert below because of
            # 'continue').
            # Don't forget to verify the diff afterwards to see if they make
            # sense though!)
            # if found_score != expected_score:
            #     filename = 'src/olympia/search/tests/test_search_ranking.py'
            #     with open('/code/tmp/sed_me.sh', 'a+') as f:
            #         f.write('sed -i s/%s/%s/ %s\n' % (
            #             expected_score, found_score, filename))
            #     continue
            assert found_score == expected_score, (
                'Expected "{}" to be on position {} with score {} but '
                '"{}" was found instead with score {} for query {}'.format(
                    expected_name, idx, expected_score, found_name, found_score, query
                )
            )

        return results

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Shouldn't be necessary, but just in case.
        cls.empty_index('default')

        # This data was taken from our production add-ons to test
        # a few search scenarios. (2018-01-25)
        # Note that it's important to set average_daily_users for extensions
        # in every case, because it affects the ranking score and otherwise
        # addon_factory() sets a random value.
        amo.tests.addon_factory(
            average_daily_users=18981,
            description=None,
            name='Tab Center Redux',
            slug='tab-center-redux',
            summary='Move your tabs to the side of your browser window.',
            weekly_downloads=915,
        )
        amo.tests.addon_factory(
            average_daily_users=468126,
            description=None,
            name='Tab Mix Plus',
            slug='tab-mix-plus',
            summary=(
                "Tab Mix Plus enhances Firefox's tab browsing capabilities. "
                'It includes such features as duplicating tabs, controlling '
                'tab focus, tab clicking options, undo closed tabs and '
                'windows, plus much more. It also includes a full-featured '
                'session manager.'
            ),
            weekly_downloads=3985,
        )
        amo.tests.addon_factory(
            average_daily_users=8838,
            description=None,
            name='Redux DevTools',
            slug='remotedev',
            summary=('DevTools for Redux with actions history, undo and replay.'),
            weekly_downloads=1032,
        )
        amo.tests.addon_factory(
            average_daily_users=482,
            description=None,
            name='Open Image in New Tab',
            slug='open-image-new-tab',
            summary='Adds a context menu to open images in a new tab.',
            weekly_downloads=158,
        )
        amo.tests.addon_factory(
            average_daily_users=2607,
            description=None,
            name='Open image in a new tab',
            slug='open-image-in-a-new-tab',
            summary='A context menu to open images in a new tab',
            weekly_downloads=329,
        )
        amo.tests.addon_factory(
            average_daily_users=27832,
            description=None,
            name='Open Bookmarks in New Tab',
            slug='open-bookmarks-in-new-tab',
            summary=(
                'After you installed this addon to your Firefox, bookmarks '
                'are opened in new tab always.'
            ),
            weekly_downloads=145,
        )
        amo.tests.addon_factory(
            average_daily_users=528,
            description=None,
            name='Coinhive Blocker',
            slug='coinhive-blocker',
            summary='Coinhive mining blocker',
            weekly_downloads=132,
        )
        amo.tests.addon_factory(
            average_daily_users=3015,
            description=None,
            name='CoinBlock',
            slug='coinblock',
            summary=(
                'With the rising popularity of coinminers in js form, this '
                'extension attempts to block those hosted on coin-hive, and '
                'cryptoloot.\nA multiple entry block list is planned.'
            ),
            weekly_downloads=658,
        )
        amo.tests.addon_factory(
            average_daily_users=418,
            description=None,
            name='NoMiners',
            slug='nominers',
            summary=(
                'NoMiners is an Add-on that tries to block cryptominers such '
                'as coinhive.\n\nBlocking those pesky miner scripts will '
                'relieve your CPU and BATTERY while browsing the web.'
                "\n\nIt's open source, so feel free to check out the code "
                'and submit improvements.'
            ),
            weekly_downloads=71,
        )
        amo.tests.addon_factory(
            average_daily_users=399485,
            description=None,
            name='Privacy Badger',
            slug='privacy-badger17',
            summary=(
                'Protects your privacy by blocking spying ads and invisible '
                'trackers.'
            ),
            weekly_downloads=22931,
        )
        amo.tests.addon_factory(
            average_daily_users=8728,
            description=None,
            name='Privacy Pass',
            slug='privacy-pass',
            summary=(
                'Handles passes containing cryptographically blinded tokens '
                'for bypassing challenge pages.'
            ),
            weekly_downloads=4599,
        )
        amo.tests.addon_factory(
            average_daily_users=15406,
            description=None,
            name='Privacy Settings',
            slug='privacy-settings',
            summary=(
                "Alter Firefox's built-in privacy settings easily with a "
                'toolbar panel.'
            ),
            weekly_downloads=1492,
        )
        amo.tests.addon_factory(
            average_daily_users=12857,
            description=None,
            name='Google Privacy',
            slug='google-privacy',
            summary=(
                'Make some popular websites respect your privacy settings.\n'
                'Please see the known issues below!'
            ),
            weekly_downloads=117,
        )
        amo.tests.addon_factory(
            average_daily_users=70553,
            description=None,
            name='Blur',
            slug='donottrackplus',
            summary='Protect your Passwords, Payments, and Privacy.',
            weekly_downloads=2224,
        )
        amo.tests.addon_factory(
            average_daily_users=1009156,
            description=None,
            name='Ghostery',
            slug='ghostery',
            summary=(
                'See who’s tracking you online and protect your privacy with '
                'Ghostery.'
            ),
            weekly_downloads=49315,
        )
        amo.tests.addon_factory(
            average_daily_users=954288,
            description=None,
            name='Firebug',
            slug='firebug',
            summary=(
                'Firebug integrates with Firefox to put a wealth of '
                'development tools at your fingertips while you browse. You '
                'can edit, debug, and monitor CSS, HTML, and JavaScript live '
                'in any web page...'
            ),
            weekly_downloads=21969,
        )
        amo.tests.addon_factory(
            average_daily_users=10821,
            description=None,
            name='Firebug Autocompleter',
            slug='firebug-autocompleter',
            summary='Firebug command line autocomplete.',
            weekly_downloads=76,
        )
        amo.tests.addon_factory(
            average_daily_users=11992,
            description=None,
            name='Firefinder for Firebug',
            slug='firefinder-for-firebug',
            summary=(
                'Finds HTML elements matching chosen CSS selector(s) or XPath '
                'expression'
            ),
            weekly_downloads=358,
        )
        amo.tests.addon_factory(
            average_daily_users=8200,
            description=None,
            name='Fire Drag',
            slug='fire-drag',
            summary='drag texts and links with/without e10s',
            weekly_downloads=506,
        )
        amo.tests.addon_factory(
            average_daily_users=61014,
            description=None,
            name='Menu Wizard',
            slug='s3menu-wizard',
            summary=(
                'Customizemenus=Helps removing, moving and renaming menus and '
                'menu items\nColorize important menu for ease of use! (use '
                'Style (CSS))\nChange or disable any of used keyboard '
                'shortcutsnSuppor=Firefox, Thunderbird and SeaMonkey'
            ),
            weekly_downloads=927,
        )
        amo.tests.addon_factory(
            average_daily_users=81237,
            description=None,
            name='Add-ons Manager Context Menu',
            slug='am-context',
            summary='Add more items to Add-ons Manager context menu.',
            weekly_downloads=169,
        )
        amo.tests.addon_factory(
            average_daily_users=51,
            description=None,
            name='Frame Demolition',
            slug='frame-demolition',
            summary=('Enabling route to load abstracted file layer in select sites.'),
            weekly_downloads=70,
        )
        amo.tests.addon_factory(
            average_daily_users=99,
            description=None,
            name='reStyle',
            slug='re-style',
            summary=(
                'A user style manager which can load local files and apply UI '
                'styles even in Firefox 57+'
            ),
            weekly_downloads=70,
        )
        amo.tests.addon_factory(
            average_daily_users=150,
            description=None,
            name='MegaUpload DownloadHelper',
            slug='megaupload-downloadhelper',
            summary=(
                'Download from MegaUpload.\nMegaUpload Download Helper will '
                'start your download once ready.\nMegaUpload Download Helper '
                'will monitor time limitations and will auto-start your '
                'download.'
            ),
            weekly_downloads=77,
        )
        amo.tests.addon_factory(
            average_daily_users=2830,
            description=None,
            name='RapidShare DownloadHelper',
            slug='rapidshare-downloadhelper',
            summary=(
                'Note from Mozilla: This add-on has been discontinued. Try '
                '<a rel="nofollow" href="https://addons.mozilla.org/firefox/'
                'addon/rapidshare-helper/">Rapidshare Helper</a> instead.\n\n'
                'RapidShare Download Helper will start your download once '
                'ready.'
            ),
            weekly_downloads=125,
        )
        amo.tests.addon_factory(
            average_daily_users=98716,
            description=None,
            name='Popup Blocker',
            slug='popup_blocker',
            summary=(
                'Prevents your web browser from opening a new window on top '
                'of the content or web site you are viewing. The Addon also '
                'supresses unwanted advertisement windows on your screen. '
                'The one deciding what consitutes a popup is the user.'
            ),
            weekly_downloads=3940,
        )
        amo.tests.addon_factory(
            average_daily_users=8830,
            description=None,
            name='No Flash',
            slug='no-flash',
            summary=(
                'Replace Youtube, Vimeo and Dailymotion Flash video players '
                'embedded on third-party website by the HTML5 counterpart '
                'when the content author still use the old style embed '
                '(Flash).\n\nSource code at <a rel="nofollow" href="https://'
                'outgoing.prod.mozaws.net/v1/14b404a3c05779fa94b24e0bffc0d710'
                '6836f1d6b771367b065fb96e9c8656b9/https%3A//github.com/hfigui'
                'ere/no-flash">https://github.com/hfiguiere/no-flash</a>'
            ),
            weekly_downloads=77,
        )
        amo.tests.addon_factory(
            average_daily_users=547880,
            description=None,
            name='Download Flash and Video',
            slug='download-flash-and-video',
            summary=(
                'Download Flash and Video is a great download helper tool '
                'that lets you download Flash games and Flash videos '
                '(YouTube, Facebook, Dailymotion, Google Videos and more) '
                'with a single click.\nThe downloader is very easy to use.'
            ),
            weekly_downloads=65891,
        )
        amo.tests.addon_factory(
            average_daily_users=158796,
            description=None,
            name='YouTube Flash Video Player',
            slug='youtube-flash-video-player',
            summary=(
                'YouTube Flash Video Player is a powerful tool that will let '
                'you choose Flash video player as default YouTube video '
                'player.'
            ),
            weekly_downloads=12239,
        )
        amo.tests.addon_factory(
            average_daily_users=206980,
            description=None,
            name='YouTube Flash Player',
            slug='youtube-flash-player',
            summary=(
                'A very lightweight add-on that allows you to watch YouTube™ '
                'videos using Flash® Player instead of the '
                'default HTML5 player. The Flash® Player will consume less '
                "CPU and RAM resources if your device doesn't easily "
                'support HTML5 videos. Try it!'
            ),
            weekly_downloads=21882,
        )
        amo.tests.addon_factory(
            average_daily_users=5056,
            description=None,
            name='Disable Hello, Pocket & Reader+',
            slug='disable-hello-pocket-reader',
            summary=(
                'Turn off Pocket, Reader, Hello and WebRTC bloatware - keep '
                'browser fast and clean'
            ),
            weekly_downloads=85,
        )
        amo.tests.addon_factory(
            average_daily_users=26135,
            description=None,
            name='Reader',
            slug='reader',
            summary='Reader is the ultimate Reader tool for Firefox.',
            weekly_downloads=2463,
        )
        amo.tests.addon_factory(
            average_daily_users=53412,
            description=None,
            name='Disable WebRTC',
            slug='happy-bonobo-disable-webrtc',
            summary=(
                'WebRTC leaks your actual IP addresses from behind your VPN, '
                'by default.'
            ),
            weekly_downloads=10583,
        )
        amo.tests.addon_factory(
            average_daily_users=12953,
            description=None,
            name='In My Pocket',
            slug='in-my-pocket',
            summary=(
                'For all those who are missing the old Firefox Pocket addon, '
                'and not satisfied with the new Pocket integration, here is '
                'an unofficial client for the excellent Pocket service. '
                "Hope you'll enjoy it!"
            ),
            weekly_downloads=1123,
        )
        amo.tests.addon_factory(
            average_daily_users=4089,
            description=None,
            name='Tabby Cat',
            slug='tabby-cat-friend',
            summary='A new friend in every new tab.',
            weekly_downloads=350,
            promoted=RECOMMENDED,
        )
        amo.tests.addon_factory(
            average_daily_users=5819,
            description=None,
            name='Authenticator',
            slug='auth-helper',
            summary=(
                'Authenticator generates 2-Step Verification codes in your browser.'
            ),
            weekly_downloads=500,
        )
        amo.tests.addon_factory(
            average_daily_users=74094,
            description=None,
            name='OneTab',
            slug='onetab',
            summary=(
                'OneTab - Too many tabs? Convert tabs to a list and reduce '
                'browser memory'
            ),
            weekly_downloads=3249,
        )
        amo.tests.addon_factory(
            average_daily_users=14968,
            description=None,
            name='FoxyTab',
            slug='foxytab',
            summary=(
                'Collection of Tab Related Actions Lorem ipsum dolor sit '
                'amet, mea dictas corpora aliquando te. Et pri docendi '
                'fuisset petentium, ne aeterno concludaturque usu, vide '
                'modus quidam per ex. Illum tempor duo eu, ut mutat noluisse '
                'consulatu vel.'
            ),
            weekly_downloads=700,
        )
        amo.tests.addon_factory(
            average_daily_users=3064,
            description=None,
            name='Simple WebSocket Client',
            slug='in-my-pocket',
            summary=(
                'Construct custom Web Socket requests and handle responses '
                'to directly test your Web Socket services.'
            ),
        )
        amo.tests.addon_factory(
            name='GrApple Yummy',
            type=amo.ADDON_EXTENSION,
            average_daily_users=1,
            weekly_downloads=1,
            summary=None,
        )
        amo.tests.addon_factory(
            name='Delicious Bookmarks',
            type=amo.ADDON_EXTENSION,
            average_daily_users=1,
            weekly_downloads=1,
            summary=None,
        )
        amo.tests.addon_factory(
            average_daily_users=101940,
            description=None,
            name='Personas Plus',
            slug='personas-plus',
            summary='Persona Plus',
        )

        # Some more or less Dummy data to test a few very specific scenarios
        # e.g for exact name matching
        amo.tests.addon_factory(
            name='Merge Windows',
            type=amo.ADDON_EXTENSION,
            average_daily_users=1,
            weekly_downloads=1,
            summary=None,
        )
        amo.tests.addon_factory(
            name='Merge All Windows',
            type=amo.ADDON_EXTENSION,
            average_daily_users=1,
            weekly_downloads=1,
            summary=None,
        )
        amo.tests.addon_factory(
            name='All Downloader Professional',
            type=amo.ADDON_EXTENSION,
            average_daily_users=1,
            weekly_downloads=1,
            summary=None,
        )

        amo.tests.addon_factory(
            name='test addon test11',
            type=amo.ADDON_EXTENSION,
            average_daily_users=1,
            weekly_downloads=1,
            summary=None,
        )
        amo.tests.addon_factory(
            name='test addon test21',
            type=amo.ADDON_EXTENSION,
            average_daily_users=1,
            weekly_downloads=1,
            summary=None,
        )
        amo.tests.addon_factory(
            name='test addon test31',
            type=amo.ADDON_EXTENSION,
            average_daily_users=1,
            weekly_downloads=1,
            summary=None,
            description='I stole test addon test21 name for my description!',
        )

        names = {
            'fr': 'Foobar unique francais',
            'en-US': 'Foobar unique english',
            'en-ca': 'Foobar unique english',
        }
        amo.tests.addon_factory(
            name=names,
            type=amo.ADDON_EXTENSION,
            default_locale='fr',
            slug='test-addon-test-special',
            average_daily_users=1,
            weekly_downloads=1,
            summary=None,
        )

        amo.tests.addon_factory(
            name='1-Click YouTube Video Download',
            type=amo.ADDON_EXTENSION,
            average_daily_users=566337,
            weekly_downloads=150000,
            summary=None,
            description=(
                'This addon contains Amazon 1-Click Lock in its description '
                ' but not in its name.'
            ),
        ),
        amo.tests.addon_factory(
            name='Amazon 1-Click Lock',
            type=amo.ADDON_EXTENSION,
            average_daily_users=50,
            weekly_downloads=1,
            summary=None,
        )

        amo.tests.addon_factory(
            average_daily_users=4089,
            description=None,
            name='Stripy Dog 1',
            slug='stripy-dog-1',
            summary='A new friend in every new window.',
            weekly_downloads=350,
            promoted=RECOMMENDED,
        )
        amo.tests.addon_factory(
            average_daily_users=4089,
            description=None,
            name='Stripy Dog 2',
            slug='stripy-dog-2',
            summary='A new friend in every new window.',
            weekly_downloads=350,
            promoted=LINE,
        )
        amo.tests.addon_factory(
            average_daily_users=4089,
            description=None,
            name='Stripy Dog 3',
            slug='stripy-dog-3',
            summary='A new friend in every new window.',
            weekly_downloads=350,
            promoted=VERIFIED,
        )
        amo.tests.addon_factory(
            average_daily_users=4089,
            description=None,
            name='Stripy Dog 4',
            slug='stripy-dog-4',
            summary='A new friend in every new window.',
            weekly_downloads=350,
        )

        cls.refresh()

    def test_scenario_tabby_cat(self):
        self._check_scenario('Tabby cat', (['Tabby Cat', 43117.04],))

    def test_scenario_tabbycat(self):
        self._check_scenario(
            'tabbycat',
            (
                ['Tabby Cat', 6298.6855],
                ['OneTab', 622.352660],
                ['Tab Mix Plus', 544.4538],
                ['FoxyTab', 533.5872],
                ['Authenticator', 481.1612],
                ['Tab Center Redux', 410.79758],
                ['Open Bookmarks in New Tab', 379.56177],
                ['Open image in a new tab', 291.76306],
                ['Open Image in New Tab', 229.28279],
            ),
        )

    def test_scenario_tabbbycat(self):
        self._check_scenario(
            'tabbbycat',
            (
                ['Tabby Cat', 6298.6855],
                ['OneTab', 622.352660],
                ['Tab Mix Plus', 544.4538],
                ['FoxyTab', 533.5872],
                ['Authenticator', 481.1612],
                ['Tab Center Redux', 410.79758],
                ['Open Bookmarks in New Tab', 379.56177],
                ['Open image in a new tab', 291.76306],
                ['Open Image in New Tab', 229.28279],
            ),
        )

    def test_scenario_tabbicat(self):
        self._check_scenario(
            'tabbicat',
            (
                ['Tabby Cat', 4938.7627],
                ['OneTab', 622.352660],
                ['Tab Mix Plus', 544.4538],
                ['FoxyTab', 533.5872],
                ['Authenticator', 481.1612],
                ['Tab Center Redux', 410.79758],
                ['Open Bookmarks in New Tab', 379.56177],
                ['Open image in a new tab', 291.76306],
                ['Open Image in New Tab', 229.28279],
            ),
        )

    def test_scenario_tab_center_redux(self):
        # Tab Mix Plus and Redux DevTools to be found in this test but we now
        # require all terms to be present through minimum_should_match on the
        # fuzzy name query (and they have nothing else to match).
        self._check_scenario('tab center redux', (['Tab Center Redux', 10784.336],))

    def test_scenario_websocket(self):
        # Should *not* find add-ons that simply mention 'Source', 'Persona',
        # or other words with just 'so' in their name.
        self._check_scenario('websocket', (['Simple WebSocket Client', 1871.3523],))

    def test_scenario_open_image_new_tab(self):
        self._check_scenario(
            'Open Image in New Tab',
            (
                ['Open Image in New Tab', 5553.028],
                ['Open image in a new tab', 1735.6191],
            ),
        )

    def test_scenario_coinhive(self):
        # TODO, should match "CoinBlock". Check word delimiting analysis maybe?
        self._check_scenario(
            'CoinHive',
            (
                ['Coinhive Blocker', 1899.6584],
                ['NoMiners', 69.78211],  # via description
                # ['CoinBlock', 0],  # via prefix search
            ),
        )

    def test_scenario_privacy(self):
        self._check_scenario(
            'Privacy',
            (
                ['Privacy Badger', 2645.5205],
                ['Google Privacy', 1922.5374],  # More users, summary
                ['Privacy Settings', 1909.5417],
                ['Privacy Pass', 1815.3016],
                ['Ghostery', 183.42003],
                ['Blur', 173.68744],
            ),
        )

    def test_scenario_firebu(self):
        # The first 3 get a higher score than for 'fireb' in the test
        # below thanks to trigram match.
        self._check_scenario(
            'firebu',
            (
                ['Firebug', 1998.017],
                ['Firefinder for Firebug', 1139.96],
                ['Firebug Autocompleter', 967.0083],
                ['Fire Drag', 793.19653],
            ),
        )

    def test_scenario_fireb(self):
        self._check_scenario(
            'fireb',
            (
                ['Firebug', 1672.0083],
                ['Firefinder for Firebug', 990.9907],
                ['Firebug Autocompleter', 829.7388],
                ['Fire Drag', 793.19653],
            ),
        )

    def test_scenario_menu_wizzard(self):
        # 'Add-ons Manager Context Menu' used to be found as well in this test
        # but we now require all terms to be present through
        # minimum_should_match on the fuzzy name query (and it has nothing else
        # to match).
        self._check_scenario(
            'Menu Wizzard', (['Menu Wizard', 1523.5862],)  # (fuzzy, typo)
        )

    def test_scenario_frame_demolition(self):
        self._check_scenario('Frame Demolition', (['Frame Demolition', 4601.814],))

    def test_scenario_demolition(self):
        # Find "Frame Demolition" via a typo
        self._check_scenario('Frame Demolition', (['Frame Demolition', 4601.814],))

    def test_scenario_restyle(self):
        self._check_scenario('reStyle', (['reStyle', 4432.1533],))

    def test_scenario_megaupload_downloadhelper(self):
        # Doesn't find "RapidShare DownloadHelper" anymore
        # since we now query by "MegaUpload AND DownloadHelper"
        self._check_scenario(
            'MegaUpload DownloadHelper', (['MegaUpload DownloadHelper', 5226.827],)
        )

    def test_scenario_downloadhelper(self):
        # No direct match, "Download Flash and Video" has
        # huge amount of users that puts it first here
        self._check_scenario(
            'DownloadHelper',
            (
                ['RapidShare DownloadHelper', 2083.029],
                ['MegaUpload DownloadHelper', 1409.281],
                ['Download Flash and Video', 915.1305],
                ['1-Click YouTube Video Download', 732.97125],
                ['All Downloader Professional', 76.08504],
            ),
        )

    def test_scenario_megaupload(self):
        self._check_scenario('MegaUpload', (['MegaUpload DownloadHelper', 1625.1984],))

    def test_scenario_no_flash(self):
        self._check_scenario(
            'No Flash',
            (
                ['No Flash', 7230.9683],
                ['Download Flash and Video', 1565.2987],
                ['YouTube Flash Player', 1370.8643],
                ['YouTube Flash Video Player', 1260.1235],
            ),
        )

        # Case should not matter.
        self._check_scenario(
            'no flash',
            (
                ['No Flash', 7230.9683],
                ['Download Flash and Video', 1565.2987],
                ['YouTube Flash Player', 1370.8643],
                ['YouTube Flash Video Player', 1260.1235],
            ),
        )

    def test_scenario_youtube_html5_player(self):
        # Both are found thanks to their descriptions (matches each individual
        # term, then get rescored with a match_phrase w/ slop.
        self._check_scenario(
            'Youtube html5 Player',
            (
                ['YouTube Flash Player', 472.92587],
                ['No Flash', 205.2885],
            ),
        )

    def test_scenario_disable_hello_pocket_reader_plus(self):
        self._check_scenario(
            'Disable Hello, Pocket & Reader+',
            (['Disable Hello, Pocket & Reader+', 8651.1045],),  # yeay!
        )

    def test_scenario_grapple(self):
        """Making sure this scenario works via the API"""
        self._check_scenario('grapple', (['GrApple Yummy', 280.32382],))

    def test_scenario_delicious(self):
        """Making sure this scenario works via the API"""
        self._check_scenario('delicious', (['Delicious Bookmarks', 313.91644],))

    def test_scenario_name_fuzzy(self):
        # Fuzzy + minimum_should_match combination means we find these 3 (only
        # 2 terms are required out of the 3)
        self._check_scenario(
            'opeb boocmarks tab',
            (
                ['Open Bookmarks in New Tab', 1124.5222],
                ['Open image in a new tab', 204.52444],
                ['Open Image in New Tab', 160.72607],
            ),
        )

    def test_score_boost_name_match(self):
        # Tests that we match directly "Merge Windows" and also find
        # "Merge All Windows" because of slop=1
        self._check_scenario(
            'merge windows',
            (
                ['Merge Windows', 1202.2235],
                ['Merge All Windows', 409.31805],
            ),
        )

        self._check_scenario(
            'merge all windows',
            (
                ['Merge All Windows', 1290.6941],
                ['Merge Windows', 188.86444],
            ),
        )

    def test_score_boost_exact_match(self):
        """Test that we rank exact matches at the top."""
        self._check_scenario(
            'test addon test21',
            (
                ['test addon test21', 1283.0007],
                ['test addon test31', 183.39906],
                ['test addon test11', 173.83998],
            ),
        )

    def test_score_boost_exact_match_description_hijack(self):
        """Test that we rank exact matches at the top."""
        self._check_scenario(
            'Amazon 1-Click Lock',
            (
                ['Amazon 1-Click Lock', 4794.2417],
                ['1-Click YouTube Video Download', 127.363266],
            ),
        )

    def test_score_boost_exact_match_in_right_language(self):
        """Test that exact matches are using the translation if possible."""
        # First in english. Straightforward: it should be an exact match, the
        # translation exists.
        self._check_scenario(
            'foobar unique english',
            (['Foobar unique english', 784.86255],),
            lang='en-US',
        )

        # Then in canadian english. Should get the same score.
        self._check_scenario(
            'foobar unique english',
            (['Foobar unique english', 784.86255],),
            lang='en-CA',
        )

        # Then in british english. This is a bit of an edge case, because the
        # add-on isn't translated in that locale, but we are still able to find
        # matches using the other english translations we have (en-US and
        # en-ca, but the returned translation will follow the default locale,
        # which is fr (our translation system isn't smart enough to return an
        # english string, even though our search system is).
        # In any case it should not boost the score over the previous searches
        # in english above.
        # Note that we need to pass expected_lang because the name object won't
        # contain the lang we requested, instead it will return an object with
        # the default_locale for this addon (fr).
        self._check_scenario(
            'foobar unique english',
            (['Foobar unique francais', 784.86255],),
            lang='en-GB',
            expected_lang='fr',
        )

        # Then check in french. Also straightforward: it should be an exact
        # match, the translation exists, it's even the default locale.
        self._check_scenario(
            'foobar unique francais',
            (['Foobar unique francais', 1065.5952],),
            lang='fr',
        )

        # Check with a language that we don't have a translation for (mn), and
        # that we do not have a language-specific analyzer for.
        # Note that we need to pass expected_lang because the name object won't
        # contain the lang we requested, instead it will return an object with
        # the default_locale for this addon (fr).
        assert 'mn' not in SEARCH_LANGUAGE_TO_ANALYZER
        assert 'mn' in settings.LANGUAGES
        self._check_scenario(
            'foobar unique francais',
            (['Foobar unique francais', 1057.3596],),
            lang='mn',
            expected_lang='fr',
        )

        # Check with a language that we don't have a translation for (ca), and
        # that we *do* have a language-specific analyzer for.
        # Note that we need to pass expected_lang because the name object won't
        # contain the lang we requested, instead it will return an object with
        # the default_locale for this addon (fr).
        assert 'ca' in SEARCH_LANGUAGE_TO_ANALYZER
        assert 'ca' in settings.LANGUAGES
        self._check_scenario(
            'foobar unique francais',
            (['Foobar unique francais', 1057.3596],),
            lang='ca',
            expected_lang='fr',
        )

        # Check with a language that we do have a translation for (en-US), but
        # we're requesting the string that matches the default locale (fr).
        # Note that the name returned follows the language requested.
        self._check_scenario(
            'foobar unique francais',
            (['Foobar unique english', 1057.3596],),
            lang='en-US',
        )

    def test_scenario_tab(self):
        self._check_scenario(
            'tab',
            (
                ['Tabby Cat', 3729.772],
                ['Tab Mix Plus', 1351.80030],
                ['OneTab', 1144.28310],
                ['Tab Center Redux', 960.8551],
                ['FoxyTab', 902.628],
                ['Open Bookmarks in New Tab', 886.82874],
                ['Open image in a new tab', 715.3191],
                ['Open Image in New Tab', 560.6783],
            ),
        )

    def test_scenario_promoted(self):
        # Other than their promoted status, the 4 addons have the same data
        self._check_scenario(
            'strip',
            (
                ['Stripy Dog 1', 2902.6985],  # recommended
                ['Stripy Dog 2', 2902.6985],  # line
                ['Stripy Dog 3', 580.5397],  # verified (no boost)
                ['Stripy Dog 4', 580.5397],  # not promoted
            ),
        )
