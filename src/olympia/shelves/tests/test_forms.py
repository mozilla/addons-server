import responses

from rest_framework.reverse import reverse as drf_reverse

from django.conf import settings
from django.core.exceptions import ValidationError

from olympia.amo.tests import TestCase
from ..forms import ShelfForm


class TestShelfForm(TestCase):
    def setUp(self):
        self.criteria_sea = '?recommended=true&sort=random&type=extension'
        self.criteria_cat = '?slug=alerts-updates'
        self.criteria_rec = '?recommended=true'
        self.criteria_404 = 'sort=users&type=statictheme'
        self.criteria_not_200 = '?sort=user&type=statictheme'
        self.criteria_empty = '?sort=users&type=theme'
        baseUrl = settings.INTERNAL_SITE_URL

        responses.add(
            responses.GET,
            baseUrl + drf_reverse('v4:addon-search') +
            self.criteria_sea,
            status=200,
            json={'count': 103})
        responses.add(
            responses.GET,
            baseUrl + drf_reverse('v4:category-list') +
            self.criteria_cat,
            status=200,
            json=[{'id': 1}, {'id': 2}])
        responses.add(
            responses.GET,
            baseUrl + drf_reverse('v4:addon-recommendations') +
            self.criteria_rec,
            status=200,
            json={'count': 4})
        responses.add(
            responses.GET,
            baseUrl + drf_reverse('v4:addon-search') +
            self.criteria_404,
            status=404,
            json={"detail": "Not found."}),
        responses.add(
            responses.GET,
            baseUrl + drf_reverse('v4:addon-search') +
            self.criteria_not_200,
            status=400,
            json=['Invalid \"sort\" parameter.'])
        responses.add(
            responses.GET,
            baseUrl + drf_reverse('v4:addon-search') +
            self.criteria_empty,
            status=200,
            json={'count': 0})

    def test_clean_search(self):
        form = ShelfForm({
            'title': 'Recommended extensions',
            'shelf_type': 'extension',
            'criteria': self.criteria_sea})
        assert form.is_valid(), form.errors
        assert form.cleaned_data['criteria'] == (
            '?recommended=true&sort=random&type=extension')

    def test_clean_categories(self):
        form = ShelfForm({
            'title': 'Alerts & Updates (Categories)',
            'shelf_type': 'categories',
            'criteria': self.criteria_cat})
        assert form.is_valid(), form.errors
        assert form.cleaned_data['criteria'] == '?slug=alerts-updates'

    def test_clean_recommendations(self):
        form = ShelfForm({
            'title': 'Recommended Add-ons',
            'shelf_type': 'recommendations',
            'criteria': self.criteria_rec})
        assert form.is_valid(), form.errors
        assert form.cleaned_data['criteria'] == '?recommended=true'

    def test_clean_returns_404(self):
        data = {
            'title': 'Popular themes',
            'shelf_type': 'theme',
            'criteria': self.criteria_404}
        form = ShelfForm(data)
        form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            u'Check criteria - No data found')

    def test_clean_returns_not_200(self):
        data = {
            'title': 'Popular themes',
            'shelf_type': 'theme',
            'criteria': self.criteria_not_200}
        form = ShelfForm(data)
        form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            u'Check criteria - Invalid \"sort\" parameter.')

    def test_clean_returns_empty(self):
        data = {
            'title': 'Popular themes',
            'shelf_type': 'theme',
            'criteria': self.criteria_empty}
        form = ShelfForm(data)
        form.is_valid()
        with self.assertRaises(ValidationError) as exc:
            form.clean()
        assert exc.exception.message == (
            u'Check criteria parameters - e.g., "type"')
