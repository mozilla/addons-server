import responses

from django.conf import settings
from django.core.exceptions import ValidationError

from olympia import amo
from olympia.amo.tests import TestCase, reverse_ns
from olympia.shelves.forms import ShelfForm


class TestShelfForm(TestCase):
    def setUp(self):
        self.criteria_sea_ext = '?promoted=recommended&sort=random&type=extension'
        self.criteria_sea_thm = '?sort=users&type=statictheme'
        self.criteria_col_ext = 'password-managers'
        self.criteria_col_thm = 'featured-personas'
        self.criteria_col_404 = 'passwordmanagers'
        self.criteria_not_200 = '?sort=user&type=extension'

        responses.add(
            responses.GET,
            reverse_ns('addon-search') + self.criteria_sea_ext,
            status=200,
            json={'count': 103},
        )
        responses.add(
            responses.GET,
            reverse_ns('addon-search') + self.criteria_sea_thm,
            status=200,
            json={'count': 103},
        )
        responses.add(
            responses.GET,
            reverse_ns(
                'collection-addon-list',
                kwargs={
                    'user_pk': settings.TASK_USER_ID,
                    'collection_slug': self.criteria_col_ext,
                },
            ),
            status=200,
            json={'count': 1},
        )
        responses.add(
            responses.GET,
            reverse_ns(
                'collection-addon-list',
                kwargs={
                    'user_pk': settings.TASK_USER_ID,
                    'collection_slug': self.criteria_col_thm,
                },
            ),
            status=200,
            json={'count': 1},
        )
        responses.add(
            responses.GET,
            reverse_ns(
                'collection-addon-list',
                kwargs={
                    'user_pk': settings.TASK_USER_ID,
                    'collection_slug': self.criteria_col_404,
                },
            ),
            status=404,
            json={'detail': 'Not found.'},
        ),
        responses.add(
            responses.GET,
            reverse_ns('addon-search') + self.criteria_not_200,
            status=400,
            json=['Invalid "sort" parameter.'],
        )

    def test_clean_search_extensions(self):
        form = ShelfForm(
            {
                'title': 'Recommended extensions',
                'endpoint': 'search',
                'addon_type': amo.ADDON_EXTENSION,
                'criteria': self.criteria_sea_ext,
                'addon_count': '0',
            },
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data['criteria'] == (
            '?promoted=recommended&sort=random&type=extension'
        )

    def test_clean_search_themes(self):
        form = ShelfForm(
            {
                'title': 'Popular themes',
                'endpoint': 'search',
                'addon_type': amo.ADDON_STATICTHEME,
                'criteria': self.criteria_sea_thm,
                'addon_count': '0',
            },
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data['criteria'] == '?sort=users&type=statictheme'

    def test_clean_collections_extensions(self):
        form = ShelfForm(
            {
                'title': 'Password managers (Collections)',
                'endpoint': 'collections',
                'addon_type': amo.ADDON_EXTENSION,
                'criteria': self.criteria_col_ext,
                'addon_count': '0',
            },
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data['criteria'] == 'password-managers'

    def test_clean_collections_themes(self):
        form = ShelfForm(
            {
                'title': 'Featured themes',
                'endpoint': 'collections',
                'addon_type': amo.ADDON_STATICTHEME,
                'criteria': self.criteria_col_thm,
                'addon_count': '0',
            },
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data['criteria'] == 'featured-personas'

    def test_clean_form_is_missing_title_field(self):
        form = ShelfForm(
            {
                'title': '',
                'endpoint': 'search',
                'addon_type': amo.ADDON_EXTENSION,
                'criteria': self.criteria_sea_ext,
                'addon_count': '0',
            },
        )
        assert not form.is_valid()
        assert form.errors == {'title': ['This field is required.']}

    def test_clean_form_is_missing_endpoint_field(self):
        form = ShelfForm(
            {
                'title': 'Recommended extensions',
                'endpoint': '',
                'addon_type': amo.ADDON_EXTENSION,
                'criteria': self.criteria_sea_ext,
                'addon_count': '0',
            },
        )
        assert not form.is_valid()
        assert form.errors == {'endpoint': ['This field is required.']}

    def test_clean_form_is_missing_addon_type_field(self):
        form = ShelfForm(
            {
                'title': 'Recommended extensions',
                'endpoint': 'search',
                'addon_type': '',
                'criteria': self.criteria_sea_ext,
                'addon_count': '0',
            },
        )
        assert not form.is_valid()
        assert form.errors == {'addon_type': ['This field is required.']}

    def test_clean_form_is_missing_addon_count_field(self):
        data = {
            'title': 'Recommended extensions',
            'endpoint': 'search',
            'addon_type': amo.ADDON_EXTENSION,
            'criteria': self.criteria_sea_ext,
        }
        form = ShelfForm(data)
        assert not form.is_valid()
        assert form.errors == {'addon_count': ['This field is required.']}

        data['addon_count'] = ''
        form = ShelfForm(data)
        assert not form.is_valid()
        assert form.errors == {'addon_count': ['This field is required.']}

        data['addon_count'] = 'aa'
        form = ShelfForm(data)
        assert not form.is_valid()
        assert form.errors == {'addon_count': ['Enter a whole number.']}

        data['addon_count'] = '0'
        form = ShelfForm(data)
        assert form.is_valid(), form.errors

    def test_clean_form_is_missing_criteria_field(self):
        form = ShelfForm(
            {
                'title': 'Recommended extensions',
                'endpoint': 'search',
                'addon_type': amo.ADDON_EXTENSION,
                'criteria': '',
                'addon_count': '0',
            },
        )
        assert not form.is_valid()
        assert form.errors == {'criteria': ['This field is required.']}

    def test_clean_search_criteria_does_not_start_with_qmark(self):
        form = ShelfForm(
            {
                'title': 'Recommended extensions',
                'endpoint': 'search',
                'addon_type': amo.ADDON_EXTENSION,
                'criteria': '..?recommended-true',
                'addon_count': '0',
            },
        )
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == ('Check criteria field.')

    def test_clean_search_criteria_has_multiple_qmark(self):
        form = ShelfForm(
            {
                'title': 'Recommended extensions',
                'endpoint': 'search',
                'addon_type': amo.ADDON_EXTENSION,
                'criteria': '??recommended-true',
                'addon_count': '0',
            },
        )
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == ('Check criteria field.')

    def test_clean_form_throws_error_for_NoReverseMatch(self):
        form = ShelfForm(
            {
                'title': 'New collection',
                'endpoint': 'collections',
                'addon_type': amo.ADDON_EXTENSION,
                'criteria': '/',
                'addon_count': '0',
            },
        )
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            'Collection not found - check criteria parameters.'
        )

    def test_clean_col_returns_404(self):
        data = {
            'title': 'Password manager (Collections)',
            'endpoint': 'collections',
            'addon_type': amo.ADDON_EXTENSION,
            'criteria': self.criteria_col_404,
            'addon_count': '0',
        }
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == ('URL was a 404. Check criteria')

    def test_clean_returns_not_200(self):
        data = {
            'title': 'Popular extensions',
            'endpoint': 'search',
            'addon_type': amo.ADDON_EXTENSION,
            'criteria': self.criteria_not_200,
            'addon_count': '0',
        }
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == ('Check criteria - Invalid "sort" parameter.')

    def test_clean_cannot_use_theme_addontype_without_type_statictheme(self):
        data = {
            'title': 'Popular themes',
            'endpoint': 'search',
            'addon_type': amo.ADDON_STATICTHEME,
            'criteria': self.criteria_sea_ext,
            'addon_count': '0',
        }
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            'Check fields - for "Theme (Static)" addon type, use type=statictheme. '
            'For non theme addons, use "Extension" in Addon type field, '
            'not "Theme (Static)".'
        )

    def test_clean_cannot_use_extensions_addontype_with_type_statictheme(self):
        data = {
            'title': 'Popular themes',
            'endpoint': 'search',
            'addon_type': amo.ADDON_EXTENSION,
            'criteria': self.criteria_sea_thm,
            'addon_count': '0',
        }
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            'Use "Theme (Static)" in Addon type field for type=statictheme.'
        )
