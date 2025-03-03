from unittest import mock

from django.conf import settings
from django.core.management import call_command

from olympia.amo.tests import TestCase, addon_factory
from olympia.translations.models import (
    LinkifiedTranslation,
    PurifiedTranslation,
    Translation,
)


class TestRebleachSummaries(TestCase):
    def setUp(self):
        self.translation_with_url = Translation.objects.get(
            id=addon_factory().summary_id
        )
        self.translation_with_url.update(
            localized_string='foo http://bar.com',
            localized_string_clean='foo <a href="http://bar.com">http://bar.com</a>',
        )
        self.translation_with_html = Translation.objects.get(
            id=addon_factory().summary_id
        )
        self.translation_with_html.update(
            localized_string='foo <a href="http://bar.com">http://bar.com</a>',
            localized_string_clean=(
                'foo &lt;a href=&quot;http://bar.com&quot;&gt;http://bar.com&lt;/a&gt;'
            ),
        )

        # We shouldn't touch that one (in particular, we shouldn't double-escape it).
        self.translation_with_already_escaped_html = Translation.objects.get(
            id=addon_factory().summary_id
        )
        self.translation_with_already_escaped_html.update(
            localized_string=(
                'foo &lt;a href=&quot;http://bar.com&quot;&gt;http://bar.com&lt;/a&gt;'
            ),
            localized_string_clean=(
                'foo &lt;a href=&quot;http://bar.com&quot;&gt;http://bar.com&lt;/a&gt;'
            ),
        )

    def test_basic(self):
        call_command('process_translations', task='strip_html_from_summaries')

        self.translation_with_url.reload()
        assert (
            self.translation_with_url.localized_string
            == self.translation_with_url.localized_string_clean
            == 'foo http://bar.com'
        )

        self.translation_with_html.reload()
        assert (
            self.translation_with_html.localized_string
            == self.translation_with_html.localized_string_clean
            == 'foo http://bar.com'
        )

        self.translation_with_already_escaped_html.reload()
        assert (
            self.translation_with_already_escaped_html.localized_string
            == self.translation_with_already_escaped_html.localized_string_clean
            == 'foo &lt;a href=&quot;http://bar.com&quot;&gt;http://bar.com&lt;/a&gt;'
        )


class TestTranslationCommands(TestCase):
    def setUp(self):
        # Create expected translations in 2 steps so that their autoid and id
        # are set as they would in production: first through .new() to create
        # the instance and "reserve" the id, then .save() to record everything
        # and generate an autoid (pk).
        self.translations = [
            # Translation that shouldn't be touched.
            Translation.new('<b>foo</b> bar', 'en-US'),
            # PurifiedTranslation that shouldn't be touched.
            PurifiedTranslation.new('<b>foo</b> bar', 'en-US'),
            # PurifiedTranslation (allows HTML) that should be updated.
            PurifiedTranslation.new(
                '<b>foo</b> https://outgoing.prod.mozaws.net/v1/bar', 'en-US'
            ),
            # LinkifiedTranslation (allows only links) that should be updated.
            LinkifiedTranslation.new(
                '<b>foo</b> https://outgoing.prod.mozaws.net/v1/bar', 'en-US'
            ),
            # PurifiedTranslation (allows HTML) that should be updated but only
            # when passing a custom outgoing url.
            PurifiedTranslation.new(
                '<b>meh</b> https://outgoing.stage.mozaws.net/v1/xyz', 'en-US'
            ),
            # LinkifiedTranslation (allows only links) that should be updated
            # but only when passing a custom outgoing url.
            LinkifiedTranslation.new(
                '<b>meh</b> https://outgoing.stage.mozaws.net/v1/xyz', 'en-US'
            ),
            # PurifiedTranslation (allows HTML) that should be updated (url is
            # present twice).
            PurifiedTranslation.new(
                '<b>foo2</b> https://outgoing.prod.mozaws.net/v1/bar '
                'https://outgoing.prod.mozaws.net/v1/bar2',
                'en-US',
            ),
            # LinkifiedTranslation (allows only links) that should be updated.
            #  (url is present twice).
            LinkifiedTranslation.new(
                '<b>foo2</b> https://outgoing.prod.mozaws.net/v1/bar '
                'https://outgoing.prod.mozaws.net/v1/bar2',
                'en-US',
            ),
        ]
        for translation in self.translations:
            translation.save()

    def test_update_outgoing_url(self):
        self.expected = {}
        for translation in self.translations:
            self.expected[translation.pk] = (
                translation.localized_string.replace(
                    'https://outgoing.prod.mozaws.net/v1/',
                    settings.REDIRECT_URL,
                ),
                translation.localized_string_clean.replace(
                    'https://outgoing.prod.mozaws.net/v1/',
                    settings.REDIRECT_URL,
                )
                if translation.localized_string_clean
                else None,
            )
        call_command('process_translations', task='update_outgoing_url')
        for pk, expected_values in self.expected.items():
            translation = Translation.objects.get(pk=pk)
            assert translation.localized_string == expected_values[0]
            assert translation.localized_string_clean == expected_values[1]

    def test_update_outgoing_url_custom_url(self):
        self.expected = {}
        for translation in self.translations:
            self.expected[translation.pk] = (
                translation.localized_string.replace(
                    'https://outgoing.stage.mozaws.net/v1/',
                    settings.REDIRECT_URL,
                ),
                translation.localized_string_clean.replace(
                    'https://outgoing.stage.mozaws.net/v1/',
                    settings.REDIRECT_URL,
                )
                if translation.localized_string_clean
                else None,
            )

        with mock.patch.dict(
            'os.environ',
            {'OLD_OUTGOING_URL': 'https://outgoing.stage.mozaws.net/v1/'},
            clear=True,
        ):
            call_command('process_translations', task='update_outgoing_url')
        for pk, expected_values in self.expected.items():
            translation = Translation.objects.get(pk=pk)
            assert translation.localized_string == expected_values[0]
            assert translation.localized_string_clean == expected_values[1]
