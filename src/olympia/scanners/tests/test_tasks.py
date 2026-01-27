import json
import os
from unittest import mock

from django.conf import settings
from django.core.files import File as DjangoFile
from django.test.utils import override_settings

import requests

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    user_factory,
    version_factory,
)
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.constants.scanners import (
    ABORTED,
    ABORTING,
    COMPLETED,
    CUSTOMS,
    NARC,
    NEW,
    RUNNING,
    SCHEDULED,
    WEBHOOK,
    WEBHOOK_DURING_VALIDATION,
    YARA,
)
from olympia.files.models import File
from olympia.files.tests.test_models import UploadMixin
from olympia.files.utils import parse_addon
from olympia.scanners.models import (
    ScannerQueryResult,
    ScannerQueryRule,
    ScannerResult,
    ScannerRule,
    ScannerWebhook,
    ScannerWebhookEvent,
)
from olympia.scanners.tasks import (
    _call_webhook,
    _run_yara,
    call_webhooks,
    call_webhooks_during_validation,
    mark_scanner_query_rule_as_completed_or_aborted,
    run_customs,
    run_narc_on_version,
    run_scanner,
    run_scanner_query_rule,
    run_scanner_query_rule_on_versions_chunk,
    run_yara,
)
from olympia.versions.models import Version


class TestRunScanner(UploadMixin, TestCase):
    FAKE_SCANNER = 1
    MOCK_SCANNERS = {FAKE_SCANNER: 'fake-scanner'}
    API_URL = 'http://scanner.example.org'
    API_KEY = 'api-key'

    def setUp(self):
        super().setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
        }

    def create_response(self, status_code=200, data=None):
        response = mock.Mock(status_code=status_code)
        response.json.return_value = data if data else {}
        return response

    @override_settings(SCANNER_TIMEOUT=123)
    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch.object(requests.Session, 'post')
    def test_run_with_mocks(self, requests_mock, incr_mock):
        rule = ScannerRule.objects.create(name='r', scanner=self.FAKE_SCANNER)
        scanner_data = {'matchedRules': [rule.name]}
        requests_mock.return_value = self.create_response(data=scanner_data)
        assert len(ScannerResult.objects.all()) == 0

        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert requests_mock.called
        requests_mock.assert_called_with(
            url=self.API_URL,
            json={
                'api_key': self.API_KEY,
                'download_url': self.upload.get_authenticated_download_url(),
            },
            timeout=123,
            headers={'Authorization': f'Bearer {self.API_KEY}'},
        )
        result = ScannerResult.objects.all()[0]
        assert result.upload == self.upload
        assert result.scanner == self.FAKE_SCANNER
        assert result.results == scanner_data
        scanner_name = self.MOCK_SCANNERS.get(self.FAKE_SCANNER)
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call(f'devhub.{scanner_name}.has_matches'),
                mock.call(f'devhub.{scanner_name}.rule.{rule.id}.match'),
                mock.call(f'devhub.{scanner_name}.success'),
            ]
        )
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch.object(requests.Session, 'post')
    def test_handles_scanner_errors_with_mocks(self, requests_mock):
        self.create_switch('ignore-exceptions-in-scanner-tasks', active=True)
        scanner_data = {'error': 'some error'}
        requests_mock.return_value = self.create_response(data=scanner_data)
        assert len(ScannerResult.objects.all()) == 0

        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert requests_mock.called
        assert len(ScannerResult.objects.all()) == 0
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch.object(requests.Session, 'post')
    def test_throws_errors_with_mocks(self, requests_mock):
        scanner_data = {'error': 'some error'}
        requests_mock.return_value = self.create_response(data=scanner_data)
        assert len(ScannerResult.objects.all()) == 0

        with self.assertRaises(ValueError):
            run_scanner(
                self.results,
                self.upload.pk,
                scanner=self.FAKE_SCANNER,
                api_url=self.API_URL,
                api_key=self.API_KEY,
            )

        assert requests_mock.called
        assert len(ScannerResult.objects.all()) == 0

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_does_not_raise(self, incr_mock):
        self.create_switch('ignore-exceptions-in-scanner-tasks', active=True)
        # This call should not raise even though there will be an error because
        # `api_url` is `None`.
        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=None,
            api_key='does-not-matter',
        )

        scanner_name = self.MOCK_SCANNERS.get(self.FAKE_SCANNER)
        assert incr_mock.called
        incr_mock.assert_called_with(f'devhub.{scanner_name}.failure')
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.statsd.timer')
    @mock.patch.object(requests.Session, 'post')
    def test_calls_statsd_timer(self, requests_mock, timer_mock):
        requests_mock.return_value = self.create_response()

        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert timer_mock.called
        scanner_name = self.MOCK_SCANNERS.get(self.FAKE_SCANNER)
        timer_mock.assert_called_with(f'devhub.{scanner_name}')
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch.object(requests.Session, 'post')
    def test_handles_http_errors_with_mock(self, requests_mock):
        self.create_switch('ignore-exceptions-in-scanner-tasks', active=True)
        requests_mock.return_value = self.create_response(
            status_code=504, data={'message': 'http timeout'}
        )
        assert len(ScannerResult.objects.all()) == 0

        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert requests_mock.called
        assert len(ScannerResult.objects.all()) == 0
        assert returned_results == self.results


class TestRunCustoms(TestCase):
    API_URL = 'http://customs.example.org'
    API_KEY = 'some-api-key'

    def setUp(self):
        super().setUp()

        self.upload_pk = 1234
        self.results = {**amo.VALIDATOR_SKELETON_RESULTS}

    @override_settings(CUSTOMS_API_URL=API_URL, CUSTOMS_API_KEY=API_KEY)
    @mock.patch('olympia.scanners.tasks.run_scanner')
    def test_calls_run_scanner_with_mock(self, run_scanner_mock):
        run_scanner_mock.return_value = self.results

        returned_results = run_customs(self.results, self.upload_pk)

        assert run_scanner_mock.called
        run_scanner_mock.assert_called_once_with(
            self.results,
            self.upload_pk,
            scanner=CUSTOMS,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )
        assert returned_results == self.results

    @override_settings(CUSTOMS_API_URL=API_URL, CUSTOMS_API_KEY=API_KEY)
    @mock.patch('olympia.scanners.tasks.run_scanner')
    def test_does_not_run_when_results_contain_errors(self, run_scanner_mock):
        self.results.update({'errors': 1})

        returned_results = run_customs(self.results, self.upload_pk)

        assert not run_scanner_mock.called
        assert returned_results == self.results


class TestRunNarc(UploadMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = user_factory(display_name='Fôo')
        self.addon = addon_factory(
            guid='@webextension-guid',
            name='My Fancy WebExtension Addon',
            users=[self.user],
        )
        upload = self.get_upload('webextension.xpi', user=self.user)
        parsed_data = parse_addon(upload, addon=self.addon, user=self.user)
        self.version = Version.from_upload(
            upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[amo.FIREFOX.id],
            parsed_data=parsed_data,
        )
        assert len(ScannerResult.objects.all()) == 0

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run(self, incr_mock):
        # This rule will match all strings, we have a user, an xpi and strings
        # in db matching so there should be 3 matches.
        rule = ScannerRule.objects.create(
            name='always_match_rule',
            scanner=NARC,
            definition='.*',
        )

        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == [rule]
        assert len(narc_result.results) == 6
        assert narc_result.results == [
            {
                'meta': {
                    'variant': 'normalized',
                    'locale': 'en-us',
                    'pattern': '.*',
                    'source': 'db_addon',
                    'span': [
                        0,
                        24,
                    ],
                    'string': 'MyFancyWebExtensionAddon',
                    'original_string': 'My Fancy WebExtension Addon',
                },
                'rule': 'always_match_rule',
            },
            {
                'meta': {
                    'locale': 'en-us',
                    'pattern': '.*',
                    'source': 'db_addon',
                    'span': [
                        0,
                        27,
                    ],
                    'string': 'My Fancy WebExtension Addon',
                },
                'rule': 'always_match_rule',
            },
            {
                'meta': {
                    'variant': 'normalized',
                    'locale': None,
                    'pattern': '.*',
                    'source': 'author',
                    'span': [
                        0,
                        3,
                    ],
                    'string': 'Foo',
                    'original_string': 'Fôo',
                },
                'rule': 'always_match_rule',
            },
            {
                'meta': {
                    'variant': 'normalized',
                    'locale': None,
                    'pattern': '.*',
                    'source': 'xpi',
                    'span': [
                        0,
                        19,
                    ],
                    'string': 'MyWebExtensionAddon',
                    'original_string': 'My WebExtension Addon',
                },
                'rule': 'always_match_rule',
            },
            {
                'meta': {
                    'span': [0, 3],
                    'locale': None,
                    'source': 'author',
                    'string': 'Fôo',
                    'pattern': '.*',
                },
                'rule': 'always_match_rule',
            },
            {
                'meta': {
                    'span': [0, 21],
                    'locale': None,
                    'source': 'xpi',
                    'string': 'My WebExtension Addon',
                    'pattern': '.*',
                },
                'rule': 'always_match_rule',
            },
        ]
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.has_matches'),
                mock.call(f'devhub.narc.rule.{rule.id}.match'),
                mock.call('devhub.narc.success'),
            ]
        )

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_normalized_match(self, incr_mock):
        self.addon.name = 'My\u2800 Fäncy WebExtension 𝕒ddon'
        self.addon.save()

        rule = ScannerRule.objects.create(
            name='always_match_rule',
            scanner=NARC,
            definition='MyFancyWebExtensionAddon',
        )

        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == [rule]
        assert len(narc_result.results) == 1
        assert narc_result.results == [
            {
                'meta': {
                    'locale': 'en-us',
                    'original_string': 'My⠀ Fäncy WebExtension 𝕒ddon',
                    'pattern': 'MyFancyWebExtensionAddon',
                    'source': 'db_addon',
                    'span': [
                        0,
                        24,
                    ],
                    'string': 'MyFancyWebExtensionaddon',
                    'variant': 'normalized',
                },
                'rule': 'always_match_rule',
            },
        ]
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.has_matches'),
                mock.call(f'devhub.narc.rule.{rule.id}.match'),
                mock.call('devhub.narc.success'),
            ]
        )

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_homoglyph_match(self, incr_mock):
        self.addon.name = 'My\u2800 Fäncy W\u0435bEx\u0442ѐnsion addon'
        self.addon.save()

        rule = ScannerRule.objects.create(
            name='always_match_rule',
            scanner=NARC,
            definition='MyFancyWebExtensionAddon',
        )

        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == [rule]
        assert len(narc_result.results) == 1
        assert narc_result.results == [
            {
                'meta': {
                    'locale': 'en-us',
                    'original_string': 'My⠀ Fäncy WеbExтѐnsion addon',
                    'pattern': 'MyFancyWebExtensionAddon',
                    'source': 'db_addon',
                    'span': [
                        0,
                        24,
                    ],
                    'string': 'myfancywebextensionaddon',
                    'variant': 'homoglyph',
                },
                'rule': 'always_match_rule',
            },
        ]
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.has_matches'),
                mock.call(f'devhub.narc.rule.{rule.id}.match'),
                mock.call('devhub.narc.success'),
            ]
        )

    @mock.patch('olympia.scanners.tasks.statsd.timer')
    def test_calls_statsd_timer(self, timer_mock):
        run_narc_on_version(self.version.pk)

        assert timer_mock.call_count == 1
        assert timer_mock.call_args[0] == ('devhub.narc',)

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_db_translation_match_only(self, incr_mock):
        self.addon.name = {
            'fr': 'Päin au chocolat',
            'de': 'German päin',
            'en-US': 'Chocolatine',
        }
        self.addon.save()
        rule = ScannerRule.objects.create(
            name='match_the_pain',
            scanner=NARC,
            definition=r'Päin.*',  # Case is ignored.
        )
        incr_mock.reset_mock()

        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == [rule]
        assert len(narc_result.results) == 2
        assert narc_result.results == [
            {
                'meta': {
                    'span': [7, 11],
                    'locale': 'de',
                    'source': 'db_addon',
                    'string': 'German päin',
                    'pattern': 'Päin.*',
                },
                'rule': 'match_the_pain',
            },
            {
                'meta': {
                    'span': [0, 16],
                    'locale': 'fr',
                    'source': 'db_addon',
                    'string': 'Päin au chocolat',
                    'pattern': 'Päin.*',
                },
                'rule': 'match_the_pain',
            },
        ]
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.has_matches'),
                mock.call(f'devhub.narc.rule.{rule.id}.match'),
                mock.call('devhub.narc.success'),
            ]
        )

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_xpi_match_only(self, incr_mock):
        rule = ScannerRule.objects.create(
            name='always_match_rule',
            scanner=NARC,
            definition='^My WebExtension.*$',
        )

        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == [rule]
        assert len(narc_result.results) == 1
        assert narc_result.results == [
            {
                'meta': {
                    'span': [0, 21],
                    'locale': None,
                    'source': 'xpi',
                    'string': 'My WebExtension Addon',
                    'pattern': '^My WebExtension.*$',
                },
                'rule': 'always_match_rule',
            },
        ]
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.has_matches'),
                mock.call(f'devhub.narc.rule.{rule.id}.match'),
                mock.call('devhub.narc.success'),
            ]
        )
        return narc_result

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_xpi_multiple_translations(self, incr_mock):
        addon = addon_factory(file_kw={'filename': 'notify-link-clicks-i18n.xpi'})
        rule = ScannerRule.objects.create(
            name='match_in_japanese', scanner=NARC, definition='を通知'
        )
        incr_mock.reset_mock()

        run_narc_on_version(addon.current_version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == addon.current_version
        assert narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == [rule]
        assert len(narc_result.results) == 1
        assert narc_result.results == [
            {
                'meta': {
                    'locale': 'ja',
                    'pattern': 'を通知',
                    'source': 'xpi',
                    'span': [
                        3,
                        6,
                    ],
                    'string': 'リンクを通知する',
                },
                'rule': 'match_in_japanese',
            },
        ]

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_xpi_no_name(self, incr_mock):
        # If somehow an XPI without a name gets scanned we shouldn't fail.
        # Validation could have been bypassed by an admin.
        addon = addon_factory(
            file_kw={'filename': 'webextension_with_no_name_in_manifest.xpi'}
        )
        ScannerRule.objects.create(
            name='match_everything', scanner=NARC, definition='.*'
        )
        incr_mock.reset_mock()

        run_narc_on_version(addon.current_version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_invalid_manifest_somehow(self, incr_mock):
        # If somehow an XPI with a entirely invalid manifest gets scanned we
        # shouldn't fail. Validation could have been bypassed by an admin.
        addon = addon_factory()
        file_ = addon.current_version.file
        filepath = os.path.join(
            settings.ROOT,
            'src/olympia/files/fixtures/files/invalid_manifest_webextension.xpi',
        )
        with open(filepath, 'rb') as f:
            file_.file = DjangoFile(f)
            file_.save()
        ScannerRule.objects.create(
            name='match_everything', scanner=NARC, definition='.*'
        )
        incr_mock.reset_mock()

        run_narc_on_version(addon.current_version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_duplicate_values(self, incr_mock):
        locales = sorted(('de', 'es-ES', 'fr', 'it', 'ja'))
        # Make the addon name 'foo' in a bunch of locales except for one.
        self.addon.name = {locale: 'foo' for locale in locales} | {'pl': 'extra'}
        self.addon.save()
        rule = ScannerRule.objects.create(
            name='match_the_fool',
            scanner=NARC,
            definition=r'^foo$',
        )

        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == [rule]
        assert len(narc_result.results) == len(locales) + 1  # author matches.
        assert narc_result.results[5] == {
            'meta': {
                'variant': 'normalized',
                'span': [0, 3],
                'locale': None,
                'source': 'author',
                'pattern': '^foo$',
                'string': 'Foo',
                'original_string': 'Fôo',
            },
            'rule': 'match_the_fool',
        }

        for result, locale in zip(narc_result.results[:-1], locales, strict=True):
            assert result == {
                'meta': {
                    'locale': locale.lower(),
                    'pattern': '^foo$',
                    'source': 'db_addon',
                    'span': [
                        0,
                        3,
                    ],
                    'string': 'foo',
                },
                'rule': 'match_the_fool',
            }

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_multiple_authors_match(self, incr_mock):
        user1 = user_factory(display_name='Foo')
        user2 = user_factory(display_name='FooBar')
        user3 = user_factory(display_name='Alice Foo')
        user4 = user_factory(display_name=None)  # Shouldn't matter.
        self.addon.authors.add(user1)
        self.addon.authors.add(user2)
        self.addon.authors.add(user3)
        self.addon.authors.add(user4)
        rule = ScannerRule.objects.create(
            name='match_the_fool',
            scanner=NARC,
            definition=r'^foo',  # Case is ignored.
        )
        incr_mock.reset_mock()

        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == [rule]
        assert len(narc_result.results) == 3
        assert narc_result.results == [
            {
                'meta': {
                    'variant': 'normalized',
                    'span': [0, 3],
                    'locale': None,
                    'source': 'author',
                    'pattern': '^foo',
                    'string': 'Foo',
                    'original_string': 'Fôo',
                },
                'rule': 'match_the_fool',
            },
            {
                'meta': {
                    'span': [0, 3],
                    'locale': None,
                    'source': 'author',
                    'string': 'Foo',
                    'pattern': '^foo',
                },
                'rule': 'match_the_fool',
            },
            {
                'meta': {
                    'locale': None,
                    'pattern': '^foo',
                    'source': 'author',
                    'span': [
                        0,
                        3,
                    ],
                    'string': 'FooBar',
                },
                'rule': 'match_the_fool',
            },
        ]
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.has_matches'),
                mock.call(f'devhub.narc.rule.{rule.id}.match'),
                mock.call('devhub.narc.success'),
            ]
        )

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_multiple_matching_rules(self, incr_mock):
        # Note that those rules contain whitespace so they won't create
        # additional results for normalized variants.
        rule1 = ScannerRule.objects.create(
            name='match_the_beginning',
            scanner=NARC,
            definition=r'^My\s.*',
        )
        rule2 = ScannerRule.objects.create(
            name='match_the_end',
            scanner=NARC,
            definition=r'WebExtension Addon$',
        )

        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == [rule1, rule2]
        assert len(narc_result.results) == 4
        assert narc_result.results == [
            {
                'meta': {
                    'locale': 'en-us',
                    'pattern': 'WebExtension Addon$',
                    'source': 'db_addon',
                    'span': [
                        9,
                        27,
                    ],
                    'string': 'My Fancy WebExtension Addon',
                },
                'rule': 'match_the_end',
            },
            {
                'meta': {
                    'locale': 'en-us',
                    'pattern': r'^My\s.*',
                    'source': 'db_addon',
                    'span': [
                        0,
                        27,
                    ],
                    'string': 'My Fancy WebExtension Addon',
                },
                'rule': 'match_the_beginning',
            },
            {
                'meta': {
                    'span': [3, 21],
                    'locale': None,
                    'source': 'xpi',
                    'string': 'My WebExtension Addon',
                    'pattern': 'WebExtension Addon$',
                },
                'rule': 'match_the_end',
            },
            {
                'meta': {
                    'span': [0, 21],
                    'locale': None,
                    'source': 'xpi',
                    'string': 'My WebExtension Addon',
                    'pattern': r'^My\s.*',
                },
                'rule': 'match_the_beginning',
            },
        ]
        assert incr_mock.called
        assert incr_mock.call_count == 4
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.has_matches'),
                mock.call(f'devhub.narc.rule.{rule1.id}.match'),
                mock.call(f'devhub.narc.rule.{rule2.id}.match'),
                mock.call('devhub.narc.success'),
            ]
        )
        return narc_result

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_no_rule(self, incr_mock):
        run_narc_on_version(self.version.pk)
        scanner_results = ScannerResult.objects.all()
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert len(narc_result.results) == 0
        assert not narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == []
        assert incr_mock.called
        assert incr_mock.call_count == 1
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.success'),
            ]
        )

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_inactive_rule_ignored(self, incr_mock):
        ScannerRule.objects.create(
            name='match_the_beginning_inactive',
            scanner=NARC,
            definition=r'^My.*',
            is_active=False,
        )
        rule2 = ScannerRule.objects.create(
            name='match_the_end',
            scanner=NARC,
            definition=r'(?<!fancy) WebExtension Addon$',
        )

        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == [rule2]
        assert len(narc_result.results) == 1
        assert narc_result.results == [
            {
                'meta': {
                    'span': [2, 21],
                    'locale': None,
                    'source': 'xpi',
                    'string': 'My WebExtension Addon',
                    'pattern': '(?<!fancy) WebExtension Addon$',
                },
                'rule': 'match_the_end',
            },
        ]
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.has_matches'),
                mock.call(f'devhub.narc.rule.{rule2.id}.match'),
                mock.call('devhub.narc.success'),
            ]
        )

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_no_match(self, incr_mock):
        ScannerRule.objects.create(
            name='does_not_match',
            scanner=NARC,
            definition=r'^something*',
        )

        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert len(narc_result.results) == 0
        assert not narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == []
        assert incr_mock.called
        assert incr_mock.call_count == 1
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.success'),
            ]
        )

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch.object(ScannerResult, 'run_action')
    def test_re_run_on_version(self, run_action_mock, incr_mock):
        # Scan a version first, make it match multiple rules.
        narc_result = self.test_run_multiple_matching_rules()
        assert len(narc_result.results) == 4
        rules = list(narc_result.matched_rules.all())

        # Add more matches through the add-on name.
        self.addon.name = {
            'fr': 'My Foolish Addon',
            'en-US': 'Another WebExtension Addon',
        }
        self.addon.save()

        incr_mock.reset_mock()
        run_action_mock.reset_mock()

        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        # New matches are added, they don't overwrite the existing ones, so we
        # should have 2 new matches.
        assert len(narc_result.results) == 6
        assert narc_result.results == [
            {
                'meta': {
                    'locale': 'en-us',
                    'pattern': 'WebExtension Addon$',
                    'source': 'db_addon',
                    'span': [
                        8,
                        26,
                    ],
                    'string': 'Another WebExtension Addon',
                },
                'rule': 'match_the_end',
            },
            # This second hit is from the initial run, that string is no longer
            # present, but we are preserving the old results.
            {
                'meta': {
                    'locale': 'en-us',
                    'pattern': 'WebExtension Addon$',
                    'source': 'db_addon',
                    'span': [
                        9,
                        27,
                    ],
                    'string': 'My Fancy WebExtension Addon',
                },
                'rule': 'match_the_end',
            },
            # Same as above.
            {
                'meta': {
                    'locale': 'en-us',
                    'pattern': r'^My\s.*',
                    'source': 'db_addon',
                    'span': [
                        0,
                        27,
                    ],
                    'string': 'My Fancy WebExtension Addon',
                },
                'rule': 'match_the_beginning',
            },
            {
                'meta': {
                    'locale': 'fr',
                    'pattern': r'^My\s.*',
                    'source': 'db_addon',
                    'span': [
                        0,
                        16,
                    ],
                    'string': 'My Foolish Addon',
                },
                'rule': 'match_the_beginning',
            },
            {
                'meta': {
                    'locale': None,
                    'pattern': 'WebExtension Addon$',
                    'source': 'xpi',
                    'span': [
                        3,
                        21,
                    ],
                    'string': 'My WebExtension Addon',
                },
                'rule': 'match_the_end',
            },
            {
                'meta': {
                    'locale': None,
                    'pattern': r'^My\s.*',
                    'source': 'xpi',
                    'span': [
                        0,
                        21,
                    ],
                    'string': 'My WebExtension Addon',
                },
                'rule': 'match_the_beginning',
            },
        ]
        assert narc_result.has_matches
        assert set(narc_result.matched_rules.all()) == set(rules)
        assert incr_mock.called
        assert incr_mock.call_count == 5
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.rerun.has_matches'),
                mock.call(f'devhub.narc.rerun.rule.{rules[0].id}.match'),
                mock.call(f'devhub.narc.rerun.rule.{rules[1].id}.match'),
                mock.call('devhub.narc.rerun.results_differ'),
                mock.call('devhub.narc.success'),
            ]
        )

        # We re-triggered the run action.
        assert run_action_mock.call_count == 1
        assert run_action_mock.call_args[0] == (self.version,)

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch.object(ScannerResult, 'run_action')
    def test_run_on_version_no_new_result(self, run_action_mock, incr_mock):
        # Scan a version first, make it one rule.
        narc_result = self.test_run_xpi_match_only()
        assert len(narc_result.results) == 1
        rules = list(narc_result.matched_rules.all())

        incr_mock.reset_mock()
        run_action_mock.reset_mock()

        # Re-run on the version.
        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        # Extra run shouldn't have caused duplicates.
        assert len(narc_result.results) == 1
        assert narc_result.has_matches
        assert rules == list(narc_result.matched_rules.all())
        rule = narc_result.matched_rules.all()[0]
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.rerun.has_matches'),
                mock.call(f'devhub.narc.rerun.rule.{rule.id}.match'),
                mock.call('devhub.narc.success'),
            ]
        )

        # We didn't retrigger the action since the first run (no new matches).
        assert run_action_mock.call_count == 0

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch.object(ScannerResult, 'run_action')
    def test_run_action_initial_run(self, run_action_mock, incr_mock):
        rule = ScannerRule.objects.create(
            name='always_match_rule',
            scanner=NARC,
            definition='^My WebExtension.*$',
        )

        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == [rule]
        assert len(narc_result.results) == 1
        assert narc_result.results == [
            {
                'meta': {
                    'span': [0, 21],
                    'locale': None,
                    'source': 'xpi',
                    'string': 'My WebExtension Addon',
                    'pattern': '^My WebExtension.*$',
                },
                'rule': 'always_match_rule',
            },
        ]
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.has_matches'),
                mock.call(f'devhub.narc.rule.{rule.id}.match'),
                mock.call('devhub.narc.success'),
            ]
        )

        assert run_action_mock.call_count == 1
        assert run_action_mock.call_args[0] == (self.version,)

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch.object(ScannerResult, 'run_action')
    def test_no_run_action_if_no_results(self, run_action_mock, incr_mock):
        run_narc_on_version(self.version.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert not narc_result.has_matches
        assert not narc_result.matched_rules.all().exists()
        assert narc_result.results == []
        assert incr_mock.call_count == 1
        assert incr_mock.call_args[0] == ('devhub.narc.success',)

        assert run_action_mock.call_count == 0

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch.object(ScannerResult, 'run_action')
    def test_no_run_action_if_parameter_is_passed(self, run_action_mock, incr_mock):
        rule = ScannerRule.objects.create(
            name='always_match_rule',
            scanner=NARC,
            definition='^My WebExtension.*$',
        )

        run_narc_on_version(self.version.pk, run_action_on_match=False)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        narc_result = scanner_results[0]
        assert narc_result.scanner == NARC
        assert narc_result.upload is None
        assert narc_result.version == self.version
        assert narc_result.has_matches
        assert list(narc_result.matched_rules.all()) == [rule]
        assert len(narc_result.results) == 1
        assert narc_result.results == [
            {
                'meta': {
                    'span': [0, 21],
                    'locale': None,
                    'source': 'xpi',
                    'string': 'My WebExtension Addon',
                    'pattern': '^My WebExtension.*$',
                },
                'rule': 'always_match_rule',
            },
        ]
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.narc.has_matches'),
                mock.call(f'devhub.narc.rule.{rule.id}.match'),
                mock.call('devhub.narc.success'),
            ]
        )

        assert run_action_mock.call_count == 0


class TestRunYara(UploadMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
        }

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0
        # This rule will match for all files in the xpi.
        rule = ScannerRule.objects.create(
            name='always_true',
            scanner=YARA,
            definition='rule always_true { condition: true }',
        )

        received_results = run_yara(self.results, self.upload.pk)

        scanner_results = ScannerResult.objects.all()
        assert len(scanner_results) == 1
        scanner_result = scanner_results[0]
        assert scanner_result.upload == self.upload
        assert len(scanner_result.results) == 2
        assert scanner_result.results[0] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': 'index.js'},
        }
        assert scanner_result.results[1] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': 'manifest.json'},
        }
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.yara.has_matches'),
                mock.call(f'devhub.yara.rule.{rule.id}.match'),
                mock.call('devhub.yara.success'),
            ]
        )
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_with_invalid_filename(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0
        # This rule will match for all files in the xpi.
        rule = ScannerRule.objects.create(
            name='always_true',
            scanner=YARA,
            definition='rule always_true { condition: true }',
        )
        self.upload = self.get_upload('archive-with-invalid-chars-in-filenames.zip')

        received_results = run_yara(self.results, self.upload.pk)

        yara_results = ScannerResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 1
        assert yara_result.results[0] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': 'path\\to\\file.txt'},
        }
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_is_json(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0
        # This rule will match for just all *.json files
        rule = ScannerRule.objects.create(
            name='json_true',
            scanner=YARA,
            # 'is_json_file' is an external variable we automatically provide.
            definition='rule json_true { condition: is_json_file and true }',
        )

        received_results = run_yara(self.results, self.upload.pk)

        yara_results = ScannerResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 1
        assert yara_result.results[0] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': 'manifest.json'},
        }
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.yara.has_matches'),
                mock.call(f'devhub.yara.rule.{rule.id}.match'),
                mock.call('devhub.yara.success'),
            ]
        )
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_is_manifest(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0
        # This rule will match for just the manifest.json
        rule = ScannerRule.objects.create(
            name='is_manifest_true',
            scanner=YARA,
            # 'is_manifest_file' is an external variable we automatically
            # provide.
            definition='rule is_manifest_true { condition: is_manifest_file }',
        )

        received_results = run_yara(self.results, self.upload.pk)

        yara_results = ScannerResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 1
        assert yara_result.results[0] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': 'manifest.json'},
        }
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.yara.has_matches'),
                mock.call(f'devhub.yara.rule.{rule.id}.match'),
                mock.call('devhub.yara.success'),
            ]
        )
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_is_locale_file(self, incr_mock):
        self.upload = self.get_upload('notify-link-clicks-i18n.xpi')
        assert len(ScannerResult.objects.all()) == 0
        # This rule will match for all _locales/*/messages.json files
        rule = ScannerRule.objects.create(
            name='is_locale_true',
            scanner=YARA,
            # 'is_locale_file' is an external variable we automatically
            # provide.
            definition='rule is_locale_true { condition: is_locale_file }',
        )

        received_results = run_yara(self.results, self.upload.pk)

        yara_results = ScannerResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 7
        assert yara_result.results[0] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/de/messages.json'},
        }
        assert yara_result.results[1] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/en/messages.json'},
        }
        assert yara_result.results[2] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/ja/messages.json'},
        }
        assert yara_result.results[3] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/nb_NO/messages.json'},
        }
        assert yara_result.results[4] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/nl/messages.json'},
        }
        assert yara_result.results[5] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/ru/messages.json'},
        }
        assert yara_result.results[6] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': '_locales/sv/messages.json'},
        }
        assert incr_mock.called
        assert incr_mock.call_count == 3
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.yara.has_matches'),
                mock.call(f'devhub.yara.rule.{rule.id}.match'),
                mock.call('devhub.yara.success'),
            ]
        )
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_no_matches(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0
        # This compiled rule will never match.
        ScannerRule.objects.create(
            name='always_false',
            scanner=YARA,
            definition='rule always_false { condition: false }',
        )

        received_results = run_yara(self.results, self.upload.pk)

        yara_result = ScannerResult.objects.all()[0]
        assert yara_result.results == []
        # The task should always return the results.
        assert received_results == self.results
        assert incr_mock.called
        assert incr_mock.call_count == 1
        incr_mock.assert_called_with('devhub.yara.success')

    def test_run_ignores_directories(self):
        upload = self.get_upload('webextension_signed_already.xpi')
        results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
        }
        # This rule will match for all files in the xpi.
        ScannerRule.objects.create(
            name='always_true',
            scanner=YARA,
            definition='rule always_true { condition: true }',
        )

        received_results = run_yara(results, upload.pk)

        yara_result = ScannerResult.objects.all()[0]
        assert yara_result.upload == upload
        # The `webextension_signed_already.xpi` fixture file has 1 directory
        # and 3 files.
        assert len(yara_result.results) == 3
        # The task should always return the results.
        assert received_results == results

    def test_run_skips_disabled_yara_rules(self):
        assert len(ScannerResult.objects.all()) == 0
        # This rule should match for all files in the xpi but it is disabled.
        ScannerRule.objects.create(
            name='always_true',
            scanner=YARA,
            definition='rule always_true { condition: true }',
            is_active=False,
        )

        run_yara(self.results, self.upload.pk)

        yara_result = ScannerResult.objects.all()[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 0

    @mock.patch('yara.compile')
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_does_not_raise(self, incr_mock, yara_compile_mock):
        self.create_switch('ignore-exceptions-in-scanner-tasks', active=True)
        yara_compile_mock.side_effect = Exception()

        # We use `_run_yara()` because `run_yara()` is decorated with
        # `@validation_task`, which gracefully handles exceptions.
        received_results = _run_yara(self.results, self.upload.pk)

        assert incr_mock.called
        incr_mock.assert_called_with('devhub.yara.failure')
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('yara.compile')
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_throws_errors(self, incr_mock, yara_compile_mock):
        yara_compile_mock.side_effect = RuntimeError()

        # We use `_run_yara()` because `run_yara()` is decorated with
        # `@validation_task`, which gracefully handles exceptions.
        with self.assertRaises(RuntimeError):
            _run_yara(self.results, self.upload.pk)

        assert incr_mock.called
        incr_mock.assert_called_with('devhub.yara.failure')

    @mock.patch('olympia.scanners.tasks.statsd.timer')
    def test_calls_statsd_timer(self, timer_mock):
        run_yara(self.results, self.upload.pk)

        assert timer_mock.called
        timer_mock.assert_called_with('devhub.yara')

    @mock.patch('yara.compile')
    def test_does_not_run_when_results_contain_errors(self, yara_compile_mock):
        self.results.update({'errors': 1})
        received_results = run_yara(self.results, self.upload.pk)

        assert not yara_compile_mock.called
        # The task should always return the results.
        assert received_results == self.results

    def test_run_in_binary_mode(self):
        self.upload = self.get_upload('webextension_with_image.zip')

        assert len(ScannerResult.objects.all()) == 0
        # This rule will match for all PNG files in the xpi.
        rule = ScannerRule.objects.create(
            name='match_png',
            scanner=YARA,
            definition='rule match_png { '
            'strings: $png = { 89 50 4E 47 0D 0A 1A 0A } '
            'condition: $png at 0 }',
        )

        received_results = run_yara(self.results, self.upload.pk)

        yara_results = ScannerResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 1
        assert yara_result.results[0] == {
            'rule': rule.name,
            'tags': [],
            'meta': {'filename': 'img.png'},
        }
        # The task should always return the results.
        assert received_results == self.results


class TestRunYaraQueryRule(TestCase):
    def setUp(self):
        super().setUp()

        self.version = addon_factory(
            name='WebExtension', file_kw={'filename': 'webextension.xpi'}
        ).current_version

        # This rule will match for all files in the xpi.
        self.rule = ScannerQueryRule.objects.create(
            name='always_true',
            scanner=YARA,
            definition='rule always_true { condition: true }',
            state=NEW,
        )

        # Just to be sure we're always starting fresh.
        assert len(ScannerQueryResult.objects.all()) == 0

    def test_run(self):
        # Pretend we went through the admin.
        self.rule.update(state=SCHEDULED)

        # Similar to test_run_on_chunk() except it needs to find the versions
        # by itself.
        other_addon = addon_factory(
            version_kw={'created': self.days_ago(1)},
            file_kw={'filename': 'webextension.xpi'},
        )
        other_addon_previous_current_version = other_addon.current_version
        included_versions = [
            # Only listed webextension version on this add-on.
            self.version,
            # Unlisted webextension version of this add-on.
            addon_factory(
                disabled_by_user=True,  # Doesn't matter.
                version_kw={'channel': amo.CHANNEL_UNLISTED},
                file_kw={'filename': 'webextension.xpi'},
            ).versions.get(),
            # Unlisted webextension version of an add-on that has multiple
            # versions.
            version_factory(
                addon=other_addon,
                created=self.days_ago(42),
                channel=amo.CHANNEL_UNLISTED,
                file_kw={'filename': 'webextension.xpi'},
            ),
            # Listed webextension versions of an add-on that has multiple
            # versions.
            other_addon_previous_current_version,
            version_factory(
                addon=other_addon, file_kw={'filename': 'webextension.xpi'}
            ),
        ]
        # Ignored versions:
        # Listed Webextension version belonging to mozilla disabled add-on.
        addon_factory(
            status=amo.STATUS_DISABLED, file_kw={'filename': 'webextension.xpi'}
        )
        # Unlisted extension without a File instance
        Version.objects.create(
            addon=other_addon, channel=amo.CHANNEL_UNLISTED, version='42.42.42.42'
        )
        # Unlisted extension with a File... but no File.file
        File.objects.create(
            manifest_version=2,
            version=Version.objects.create(
                addon=other_addon, channel=amo.CHANNEL_UNLISTED, version='43.43.43.43'
            ),
        )

        # Run the task.
        run_scanner_query_rule.delay(self.rule.pk)

        assert ScannerQueryResult.objects.count() == len(included_versions)
        assert sorted(
            ScannerQueryResult.objects.values_list('version_id', flat=True)
        ) == sorted(v.pk for v in included_versions)
        self.rule.reload()
        assert self.rule.state == COMPLETED
        assert self.rule.task_count == 1
        # We run tests in eager mode, so we can't retrieve the result for real,
        # just make sure the id was set to something.
        assert self.rule.celery_group_result_id is not None

    def test_run_on_disabled_addons(self):
        self.version.addon.update(status=amo.STATUS_DISABLED)
        self.rule.update(run_on_disabled_addons=True, state=SCHEDULED)
        run_scanner_query_rule.delay(self.rule.pk)

        assert ScannerQueryResult.objects.count() == 1
        assert ScannerQueryResult.objects.get().version == self.version
        self.rule.reload()
        assert self.rule.state == COMPLETED

    def test_exclude_promoted_addons(self):
        self.make_addon_promoted(
            self.version.addon, group_id=PROMOTED_GROUP_CHOICES.NOTABLE
        )
        self.rule.update(exclude_promoted_addons=True, state=SCHEDULED)
        run_scanner_query_rule.delay(self.rule.pk)

        assert ScannerQueryResult.objects.count() == 0
        self.rule.reload()
        assert self.rule.state == COMPLETED

    def test_run_on_current_version_only(self):
        # Pretend we went through the admin, run on current version only.
        self.rule.update(state=SCHEDULED, run_on_current_version_only=True)

        # Similar to test_run_on_chunk() except it needs to find the versions
        # by itself.
        other_addon = addon_factory(
            version_kw={'created': self.days_ago(1)},
            file_kw={'filename': 'webextension.xpi'},
        )
        included_versions = [
            self.version,
            other_addon.current_version,
        ]
        # Ignored versions:
        version_factory(
            addon=other_addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'filename': 'webextension.xpi'},
        )
        (
            version_factory(
                addon=other_addon,
                created=self.days_ago(42),
                file_kw={'filename': 'webextension.xpi'},
            ),
        )
        # Listed Webextension version belonging to mozilla disabled add-on.
        addon_factory(
            status=amo.STATUS_DISABLED, file_kw={'filename': 'webextension.xpi'}
        )
        # Listed extension without a File instance
        addon_factory(
            version_kw={'channel': amo.CHANNEL_LISTED, 'version': '42.42.42.42'}
        )

        # Run the task.
        run_scanner_query_rule.delay(self.rule.pk)

        assert ScannerQueryResult.objects.count() == len(included_versions)
        assert sorted(
            ScannerQueryResult.objects.values_list('version_id', flat=True)
        ) == sorted(v.pk for v in included_versions)
        self.rule.reload()
        assert self.rule.state == COMPLETED
        assert self.rule.task_count == 1
        # We run tests in eager mode, so we can't retrieve the result for real,
        # just make sure the id was set to something.
        assert self.rule.celery_group_result_id is not None

    def test_run_on_specific_channel(self):
        # Pretend we went through the admin, run on unlisted channel only.
        self.rule.update(state=SCHEDULED, run_on_specific_channel=amo.CHANNEL_UNLISTED)

        # Similar to test_run_on_chunk() except it needs to find the versions
        # by itself.
        other_addon = addon_factory(
            version_kw={'created': self.days_ago(1)},
            file_kw={'filename': 'webextension.xpi'},
        )
        included_versions = [
            # Only unlisted webextension version of this add-on.
            addon_factory(
                disabled_by_user=True,  # Doesn't matter.
                version_kw={'channel': amo.CHANNEL_UNLISTED},
                file_kw={'filename': 'webextension.xpi'},
            ).versions.get(),
            # Only unlisted webextension version of an add-on that has multiple
            # versions.
            version_factory(
                addon=other_addon,
                created=self.days_ago(42),
                channel=amo.CHANNEL_UNLISTED,
                file_kw={'filename': 'webextension.xpi'},
            ),
        ]
        # Ignored versions:
        # Listed Webextension version belonging to mozilla disabled add-on.
        addon_factory(file_kw={'filename': 'webextension.xpi'})
        # Unlisted extension without a File instance
        Version.objects.create(
            addon=other_addon, channel=amo.CHANNEL_UNLISTED, version='42.42.42.42'
        )
        # Unlisted extension with a File... but no File.file
        File.objects.create(
            manifest_version=2,
            version=Version.objects.create(
                addon=other_addon, channel=amo.CHANNEL_UNLISTED, version='43.43.43.43'
            ),
        )

        # Run the task.
        run_scanner_query_rule.delay(self.rule.pk)

        assert ScannerQueryResult.objects.count() == len(included_versions)
        assert sorted(
            ScannerQueryResult.objects.values_list('version_id', flat=True)
        ) == sorted(v.pk for v in included_versions)
        self.rule.reload()
        assert self.rule.state == COMPLETED
        assert self.rule.task_count == 1
        # We run tests in eager mode, so we can't retrieve the result for real,
        # just make sure the id was set to something.
        assert self.rule.celery_group_result_id is not None

    def test_run_not_new(self):
        self.rule.update(state=RUNNING)  # Not SCHEDULED.
        run_scanner_query_rule.delay(self.rule.pk)

        # Nothing should have changed.
        assert ScannerQueryResult.objects.count() == 0
        self.rule.reload()
        assert self.rule.state == RUNNING

    def test_mark_scanner_query_rule_as_completed(self):
        self.rule.update(state=RUNNING)
        mark_scanner_query_rule_as_completed_or_aborted(self.rule.pk)
        self.rule.reload()
        assert self.rule.state == COMPLETED

    def test_mark_scanner_query_rule_as_aborted(self):
        self.rule.update(state=ABORTING)
        mark_scanner_query_rule_as_completed_or_aborted(self.rule.pk)
        self.rule.reload()
        assert self.rule.state == ABORTED

    def test_run_on_chunk_aborting(self):
        self.rule.update(state=ABORTING)
        run_scanner_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)

        assert ScannerQueryResult.objects.count() == 0

        self.rule.reload()
        assert self.rule.state == ABORTING  # Not touched by this.

    def test_run_on_chunk_aborted(self):
        # This shouldn't happen - if there are any tasks left, state should be
        # RUNNING or ABORTING, but let's make sure we handle it.
        self.rule.update(state=ABORTED)
        run_scanner_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)

        assert ScannerQueryResult.objects.count() == 0
        self.rule.reload()
        assert self.rule.state == ABORTED  # Not touched by this.

    def test_run_on_chunk(self):
        self.rule.update(state=RUNNING)  # Pretend we started running the rule.
        run_scanner_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)

        yara_results = ScannerQueryResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.version == self.version
        assert not yara_result.was_blocked
        assert not yara_result.was_promoted
        assert len(yara_result.results) == 2
        assert yara_result.results[0] == {
            'rule': self.rule.name,
            'tags': [],
            'meta': {'filename': 'index.js'},
        }
        assert yara_result.results[1] == {
            'rule': self.rule.name,
            'tags': [],
            'meta': {'filename': 'manifest.json'},
        }
        self.rule.reload()
        assert self.rule.state == RUNNING  # Not touched by this task.

    def test_run_on_chunk_was_blocked(self):
        self.rule.update(state=RUNNING)  # Pretend we started running the rule.
        block_factory(addon=self.version.addon, updated_by=user_factory())
        run_scanner_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)

        scanner_results = ScannerQueryResult.objects.all()
        assert len(scanner_results) == 1
        scanner_result = scanner_results[0]
        assert scanner_result.version == self.version
        assert scanner_result.was_blocked

    def test_run_on_chunk_not_blocked(self):
        self.rule.update(state=RUNNING)  # Pretend we started running the rule.
        self.version.update(version='2.0')
        another_version = version_factory(
            addon=self.version.addon, channel=amo.CHANNEL_UNLISTED
        )
        block_factory(
            addon=self.version.addon,
            updated_by=user_factory(),
            version_ids=[another_version.id],
        )
        block_factory(
            addon=addon_factory(guid='@differentguid'),
            updated_by=user_factory(),
        )
        run_scanner_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)

        scanner_results = ScannerQueryResult.objects.all()
        assert len(scanner_results) == 1
        scanner_result = scanner_results[0]
        assert scanner_result.version == self.version
        assert not scanner_result.was_blocked

    def test_run_on_chunk_was_promoted(self):
        self.rule.update(state=RUNNING)  # Pretend we started running the rule.
        self.make_addon_promoted(
            self.version.addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        run_scanner_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)

        scanner_results = ScannerQueryResult.objects.all()
        assert len(scanner_results) == 1
        scanner_result = scanner_results[0]
        assert scanner_result.version == self.version
        assert scanner_result.was_promoted

    def test_run_on_chunk_disabled(self):
        # Make sure it still works when a file has been disabled
        File.objects.filter(pk=self.version.file.pk).update(status=amo.STATUS_DISABLED)
        self.test_run_on_chunk()

    def test_dont_generate_results_if_not_matching_rule(self):
        # Unlike "regular" ScannerRule/ScannerResult, for query stuff we don't
        # store a result instance if the version doesn't match the rule.
        self.rule.update(definition='rule always_false { condition: false }')
        run_scanner_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)
        assert ScannerQueryResult.objects.count() == 0
        self.rule.reload()
        assert self.rule.state == NEW  # Not touched by this task.


class TestRunNarcQueryRule(TestRunYaraQueryRule):
    def setUp(self):
        super().setUp()

        # Make the test rule a NARC rule.
        self.rule.update(
            name='match_everything',
            scanner=NARC,
            definition='.*',
            state=NEW,
        )

        # Just to be sure we're always starting fresh.
        assert len(ScannerQueryResult.objects.all()) == 0

    def test_run_on_chunk(self):
        self.rule.update(state=RUNNING)  # Pretend we started running the rule.
        run_scanner_query_rule_on_versions_chunk([self.version.pk], self.rule.pk)

        scanner_results = ScannerQueryResult.objects.all()
        assert len(scanner_results) == 1
        scanner_result = scanner_results.get()
        assert scanner_result.version == self.version
        assert not scanner_result.was_blocked
        assert len(scanner_result.results) == 3
        assert scanner_result.results == [
            {
                'meta': {
                    'locale': 'en-us',
                    'pattern': '.*',
                    'source': 'db_addon',
                    'span': [
                        0,
                        12,
                    ],
                    'string': 'WebExtension',
                },
                'rule': 'match_everything',
            },
            {
                'meta': {
                    'locale': None,
                    'original_string': 'My WebExtension Addon',
                    'pattern': '.*',
                    'source': 'xpi',
                    'span': [
                        0,
                        19,
                    ],
                    'string': 'MyWebExtensionAddon',
                    'variant': 'normalized',
                },
                'rule': 'match_everything',
            },
            {
                'meta': {
                    'locale': None,
                    'pattern': '.*',
                    'source': 'xpi',
                    'span': [
                        0,
                        21,
                    ],
                    'string': 'My WebExtension Addon',
                },
                'rule': 'match_everything',
            },
        ]
        self.rule.reload()
        assert self.rule.state == RUNNING  # Not touched by this task.


class TestCallWebhooks(UploadMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.upload = self.get_upload('webextension.xpi')

    @mock.patch('olympia.scanners.tasks._call_webhook')
    def test_call_webhooks(self, _call_webhook_mock):
        assert len(ScannerResult.objects.all()) == 0

        webhook_1 = ScannerWebhook.objects.create(
            name='some-scanner',
            url='https://example.org/webhook',
            api_key='some-api-key',
            is_active=True,
        )
        # This one is disabled.
        webhook_2 = ScannerWebhook.objects.create(
            name='some-disabled-scanner',
            url='https://example.org/webhook',
            api_key='some-api-key',
            is_active=False,
        )
        webhook_3 = ScannerWebhook.objects.create(
            name='some-other-scanner',
            url='https://example.org/webhook',
            api_key='some-api-key',
            is_active=True,
        )
        # Register the webhook scanners for the same event.
        event_1 = ScannerWebhookEvent.objects.create(
            event=WEBHOOK_DURING_VALIDATION, webhook=webhook_1
        )
        _event_2 = ScannerWebhookEvent.objects.create(
            event=WEBHOOK_DURING_VALIDATION, webhook=webhook_2
        )
        event_3 = ScannerWebhookEvent.objects.create(
            event=WEBHOOK_DURING_VALIDATION, webhook=webhook_3
        )

        returned_data = {'data': 'some data returned by the scanner'}
        _call_webhook_mock.return_value = returned_data

        payload = {'some': 'payload to send to the scanners for that event'}

        # Call the webhooks.
        call_webhooks(WEBHOOK_DURING_VALIDATION, payload)

        assert _call_webhook_mock.called
        assert _call_webhook_mock.call_count == 2
        _call_webhook_mock.assert_has_calls(
            [
                mock.call(webhook=webhook_1, payload=payload),
                mock.call(webhook=webhook_3, payload=payload),
            ]
        )
        results = ScannerResult.objects.all()
        assert len(results) == 2
        for result in results:
            assert result.scanner == WEBHOOK
            assert result.results == returned_data
        assert results[0].webhook_event == event_1
        assert results[1].webhook_event == event_3

    @mock.patch('olympia.scanners.tasks._call_webhook')
    def test_call_webhooks_raises(self, _call_webhook_mock):
        assert len(ScannerResult.objects.all()) == 0

        webhook = ScannerWebhook.objects.create(
            name='some-scanner',
            url='https://example.org/webhook',
            api_key='some-api-key',
            is_active=True,
        )
        ScannerWebhookEvent.objects.create(
            event=WEBHOOK_DURING_VALIDATION, webhook=webhook
        )

        _call_webhook_mock.side_effect = RuntimeError()

        payload = {'some': 'payload to send to the scanners for that event'}

        with self.assertRaises(RuntimeError):
            call_webhooks(WEBHOOK_DURING_VALIDATION, payload)


class TestCallWebhook(TestCase):
    def create_response(self, status_code=200, data=None):
        response = mock.Mock(status_code=status_code)
        response.json.return_value = data if data else {}
        return response

    @override_settings(SCANNER_TIMEOUT=123)
    @mock.patch.object(requests.Session, 'post')
    def test_call_webhook(self, requests_mock):
        webhook = ScannerWebhook.objects.create(
            name='some-scanner',
            url='https://example.org/webhook',
            api_key='some-api-key',
            is_active=True,
        )
        payload = {'some': 'payload to send to the scanners for that event'}

        response_data = {'some': 'data'}
        requests_mock.return_value = self.create_response(data=response_data)

        returned_value = _call_webhook(webhook, payload)

        assert requests_mock.called
        expected_digest = (
            '1987be0ea649633a3eaca7c504b9995fe20aa054d7423e490df927b1ede917a1'
        )
        requests_mock.assert_called_with(
            url=webhook.url,
            data=json.dumps(payload),
            timeout=123,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'HMAC-SHA256 {expected_digest}',
            },
        )
        assert returned_value == response_data

    @override_settings(SCANNER_TIMEOUT=123)
    @mock.patch.object(requests.Session, 'post')
    def test_call_webhook_http_201(self, requests_mock):
        webhook = ScannerWebhook.objects.create(
            name='some-scanner',
            url='https://example.org/webhook',
            api_key='some-api-key',
            is_active=True,
        )
        response_data = {'some': 'data'}
        requests_mock.return_value = self.create_response(
            status_code=201, data=response_data
        )

        returned_value = _call_webhook(webhook, payload={})

        assert requests_mock.called
        assert returned_value == response_data

    @override_settings(SCANNER_TIMEOUT=123)
    @mock.patch.object(requests.Session, 'post')
    def test_call_webhook_http_202(self, requests_mock):
        webhook = ScannerWebhook.objects.create(
            name='some-scanner',
            url='https://example.org/webhook',
            api_key='some-api-key',
            is_active=True,
        )
        response_data = {'some': 'data'}
        requests_mock.return_value = self.create_response(
            status_code=202, data=response_data
        )

        returned_value = _call_webhook(webhook, payload={})

        assert requests_mock.called
        assert returned_value == response_data

    @override_settings(SCANNER_TIMEOUT=123)
    @mock.patch.object(requests.Session, 'post')
    def test_call_webhook_with_error_returned_by_the_scanner(self, requests_mock):
        webhook = ScannerWebhook.objects.create(
            name='some-scanner',
            url='https://example.org/webhook',
            api_key='some-api-key',
            is_active=True,
        )
        payload = {'some': 'payload to send to the scanners for that event'}

        response_data = {'error': 'ooops'}
        requests_mock.return_value = self.create_response(data=response_data)

        with self.assertRaises(ValueError) as exc:
            _call_webhook(webhook, payload)

        assert requests_mock.called
        assert exc.exception.args[0] == response_data

    @override_settings(SCANNER_TIMEOUT=123)
    @mock.patch.object(requests.Session, 'post')
    def test_call_webhook_with_http_error(self, requests_mock):
        webhook = ScannerWebhook.objects.create(
            name='some-scanner',
            url='https://example.org/webhook',
            api_key='some-api-key',
            is_active=True,
        )
        payload = {'some': 'payload to send to the scanners for that event'}

        response_data = {'message': 'http timeout'}
        requests_mock.return_value = self.create_response(
            status_code=504, data=response_data
        )

        with self.assertRaises(ValueError) as exc:
            _call_webhook(webhook, payload)

        assert requests_mock.called
        assert exc.exception.args[0] == response_data


class TestCallWebhooksDuringValidation(UploadMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
        }

    @mock.patch('olympia.scanners.tasks.call_webhooks')
    def test_call_webhooks_during_validation(self, call_webhooks_mock):
        results = call_webhooks_during_validation(self.results, self.upload.pk)

        assert call_webhooks_mock.called
        call_webhooks_mock.assert_called_with(
            event_name=WEBHOOK_DURING_VALIDATION,
            payload={'download_url': self.upload.get_authenticated_download_url()},
            upload=self.upload,
        )
        assert self.results == results

    def test_call_webhooks_during_validation_without_file_path(self):
        self.create_switch('ignore-exceptions-in-scanner-tasks', active=False)
        self.upload.update(path='/not-a-file')

        results = call_webhooks_during_validation(self.results, self.upload.pk)

        assert self.results != results
        # This is coming from `VALIDATOR_SKELETON_EXCEPTION_WEBEXT` because
        # `call_webhooks_during_validation` is decorated with
        # `@validation_task`, which handles all uncaught exceptions gracefully.
        #
        # This is the case here since the task raises when the file upload path
        # doesn't exist.
        assert results['messages'][0]['uid'] == '35432f419340461897aa8362398339c4'

    def test_call_webhooks_during_validation_without_file_path_ignore_exceptions(self):
        self.create_switch('ignore-exceptions-in-scanner-tasks', active=True)
        self.upload.update(path='/not-a-file')

        results = call_webhooks_during_validation(self.results, self.upload.pk)

        assert self.results == results
