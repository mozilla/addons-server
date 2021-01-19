import responses

from django.conf import settings
from django.core.exceptions import ValidationError

from olympia.amo.tests import TestCase, reverse_ns
from olympia.shelves.forms import ShelfForm


class TestShelfForm(TestCase):
    def setUp(self):
        self.criteria_sea = '?promoted=recommended&sort=random&type=extension'
        self.criteria_col = 'password-managers'
        self.criteria_col_404 = 'passwordmanagers'
        self.criteria_not_200 = '?sort=user&type=extension'
        self.criteria_empty = '?sort=users&type=theme'

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
        responses.add(
            responses.GET,
            reverse_ns('addon-search') + self.criteria_empty,
            status=200,
            json={'count': 0},
        )

    def test_clean_search(self):
        form = ShelfForm(
            {
                'title': 'Recommended extensions',
                'endpoint': 'search',
                'criteria': self.criteria_sea,
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
                'criteria': self.criteria_col,
            },
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data['criteria'] == 'password-managers'

    def test_clean_form_is_missing_title_field(self):
        form = ShelfForm(
            {'title': '', 'endpoint': 'search', 'criteria': self.criteria_sea},
        )
        assert not form.is_valid()
        assert form.errors == {'title': ['This field is required.']}

    def test_clean_form_is_missing_endpoint_field(self):
        form = ShelfForm(
            {
                'title': 'Recommended extensions',
                'endpoint': '',
                'criteria': self.criteria_sea,
            },
        )
        assert not form.is_valid()
        assert form.errors == {'endpoint': ['This field is required.']}

    def test_clean_form_is_missing_criteria_field(self):
        form = ShelfForm(
            {'title': 'Recommended extensions', 'endpoint': 'search', 'criteria': ''},
        )
        assert not form.is_valid()
        assert form.errors == {'criteria': ['This field is required.']}

    def test_clean_search_criteria_does_not_start_with_qmark(self):
        form = ShelfForm(
            {
                'title': 'Recommended extensions',
                'endpoint': 'search',
                'criteria': '..?recommended-true',
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
                'criteria': '??recommended-true',
            },
        )
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == ('Check criteria field.')

    def test_clean_searchtheme_criteria_theme_used_for_statictheme_type(self):
        form = ShelfForm(
            {
                'title': 'Recommended extensions',
                'endpoint': 'search',
                'criteria': '?recommended=true&type=statictheme',
            }
        )
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            'Use "search-themes" endpoint for type=statictheme.'
        )

    def test_clean_searchtheme_criteria_theme_not_used_for_other_type(self):
        form = ShelfForm(
            {
                'title': 'Recommended extensions',
                'endpoint': 'search-themes',
                'criteria': '?recommended=true&type=extension',
            }
        )
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            'Don`t use "search-themes" endpoint for non themes. Use "search".'
        )

    def test_clean_form_throws_error_for_NoReverseMatch(self):
        form = ShelfForm(
            {'title': 'New collection', 'endpoint': 'collections', 'criteria': '/'},
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
            'criteria': self.criteria_col_404,
        }
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == ('URL was a 404. Check criteria')

    def test_clean_returns_not_200(self):
        data = {
            'title': 'Popular themes',
            'endpoint': 'search',
            'criteria': self.criteria_not_200,
        }
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == ('Check criteria - Invalid "sort" parameter.')

    def test_clean_returns_empty(self):
        data = {
            'title': 'Popular themes',
            'endpoint': 'search',
            'criteria': self.criteria_empty,
        }
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            'No add-ons found. Check criteria parameters - e.g., "type"'
        )
