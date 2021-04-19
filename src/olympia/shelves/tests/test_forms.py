import responses

from django.conf import settings
from django.core.exceptions import ValidationError

from olympia.amo.tests import TestCase, reverse_ns
from olympia.shelves.forms import ShelfForm


class TestShelfForm(TestCase):
    def setUp(self):
        self.criteria_sea = '?promoted=recommended&sort=random&type=extension'
        self.criteria_theme = '?sort=users&type=statictheme'
        self.criteria_col = 'password-managers'
        self.criteria_col_404 = 'passwordmanagers'
        self.criteria_not_200 = '?sort=user&type=extension'

        responses.add(
            responses.GET,
            reverse_ns('addon-search') + self.criteria_sea,
            status=200,
            json={'count': 103},
        )
        responses.add(
            responses.GET,
            reverse_ns(
                'collection-addon-list',
                kwargs={
                    'user_pk': settings.TASK_USER_ID,
                    'collection_slug': self.criteria_col,
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

    def test_clean_search(self):
        form = ShelfForm(
            {
                'title': 'Recommended extensions',
                'endpoint': 'search',
                'addon_type': 1,
                'criteria': self.criteria_sea,
                'addon_count': '0',
            },
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data['criteria'] == (
            '?promoted=recommended&sort=random&type=extension'
        )

    def test_clean_collections(self):
        form = ShelfForm(
            {
                'title': 'Password managers (Collections)',
                'endpoint': 'collections',
                'addon_type': 1,
                'criteria': self.criteria_col,
                'addon_count': '0',
            },
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data['criteria'] == 'password-managers'

    def test_clean_form_is_missing_title_field(self):
        form = ShelfForm(
            {
                'title': '',
                'endpoint': 'search',
                'addon_type': 1,
                'criteria': self.criteria_sea,
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
                'addon_type': 1,
                'criteria': self.criteria_sea,
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
                'criteria': self.criteria_sea,
                'addon_count': '0',
            },
        )
        assert not form.is_valid()
        assert form.errors == {'addon_type': ['This field is required.']}

    def test_clean_form_is_missing_addon_count_field(self):
        data = {
            'title': 'Recommended extensions',
            'endpoint': 'search',
            'addon_type': 1,
            'criteria': self.criteria_sea,
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
                'addon_type': 1,
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
                'addon_type': 1,
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
                'addon_type': 1,
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
                'addon_type': 1,
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
            'addon_type': 1,
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
            'addon_type': 1,
            'criteria': self.criteria_not_200,
            'addon_count': '0',
        }
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == ('Check criteria - Invalid "sort" parameter.')

    def test_clean_themes_addontype_used_for_statictheme_type(self):
        data = {
            'title': 'Recommended extensions',
            'endpoint': 'search',
            'addon_type': 10,
            'criteria': self.criteria_sea,
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

    def test_clean_extensions_addontype_not_used_for_statictheme_type(self):
        data = {
            'title': 'Popular themes',
            'endpoint': 'search',
            'addon_type': 1,
            'criteria': self.criteria_theme,
            'addon_count': '0',
        }
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            'Use "Theme (Static)" in Addon type field for type=statictheme.'
        )
