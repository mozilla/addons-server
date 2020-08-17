import responses

from django.conf import settings
from django.core.exceptions import ValidationError

from olympia.amo.tests import TestCase, reverse_ns
from olympia.shelves.forms import ShelfForm


class TestShelfForm(TestCase):
    def setUp(self):
        self.criteria_sea = '?recommended=true&sort=random&type=extension'
        self.criteria_col = 'password-managers'
        self.criteria_col_404 = 'passwordmanagers'
        self.criteria_404 = 'sort=users&type=statictheme'
        self.criteria_not_200 = '?sort=user&type=statictheme'
        self.criteria_empty = '?sort=users&type=theme'

        responses.add(
            responses.GET,
            reverse_ns('addon-search', api_version='v4') + self.criteria_sea,
            status=200,
            json={'count': 103})
        responses.add(
            responses.GET,
            reverse_ns('collection-addon-list', api_version='v4', kwargs={
                'user_pk': settings.TASK_USER_ID,
                'collection_slug': self.criteria_col}),
            status=200,
            json={'count': 1})
        responses.add(
            responses.GET,
            reverse_ns('addon-search', api_version='v4') + self.criteria_404,
            status=404,
            json={"detail": "Not found."}),
        responses.add(
            responses.GET,
            reverse_ns('collection-addon-list', api_version='v4', kwargs={
                'user_pk': settings.TASK_USER_ID,
                'collection_slug': self.criteria_col_404}),
            status=404,
            json={"detail": "Not found."}),
        responses.add(
            responses.GET,
            reverse_ns('addon-search', api_version='v4') +
            self.criteria_not_200,
            status=400,
            json=['Invalid \"sort\" parameter.'])
        responses.add(
            responses.GET,
            reverse_ns('addon-search', api_version='v4') + self.criteria_empty,
            status=200,
            json={'count': 0})

    def test_clean_search(self):
        form = ShelfForm({
            'title': 'Recommended extensions',
            'endpoint': 'search',
            'criteria': self.criteria_sea})
        assert form.is_valid(), form.errors
        assert form.cleaned_data['criteria'] == (
            '?recommended=true&sort=random&type=extension')

    def test_clean_collections(self):
        form = ShelfForm({
            'title': 'Password managers (Collections)',
            'endpoint': 'collections',
            'criteria': self.criteria_col})
        assert form.is_valid(), form.errors
        assert form.cleaned_data['criteria'] == 'password-managers'

    def test_clean_form_is_missing_required_field(self):
        form = ShelfForm({
            'title': 'Recommended extensions',
            'endpoint': '',
            'criteria': self.criteria_sea})
        assert not form.is_valid()
        assert form.errors == {'endpoint': ['This field is required.']}

    def test_clean_search_returns_404(self):
        data = {
            'title': 'Popular themes',
            'endpoint': 'search',
            'criteria': self.criteria_404}
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            'Check criteria - No data found')

    def test_clean_col_returns_404(self):
        data = {
            'title': 'Password manager (Collections)',
            'endpoint': 'collections',
            'criteria': self.criteria_col_404}
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            'Check criteria - No data found')

    def test_clean_returns_not_200(self):
        data = {
            'title': 'Popular themes',
            'endpoint': 'search',
            'criteria': self.criteria_not_200}
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            'Check criteria - Invalid \"sort\" parameter.')

    def test_clean_returns_empty(self):
        data = {
            'title': 'Popular themes',
            'endpoint': 'search',
            'criteria': self.criteria_empty}
        form = ShelfForm(data)
        assert not form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            'Check criteria parameters - e.g., "type"')
