from django.conf import settings
from django.urls import reverse

from olympia.amo.tests import TestCase


class TestPages(TestCase):
    def _check(self, url, status):
        response = self.client.get(reverse(url))
        assert response.status_code == status

    def test_search_console(self):
        response = self.client.get('/google231a41e803e464e9.html')
        assert response.status_code == 200


class TestRedirects(TestCase):
    def _check(self, pages):
        for old, new in pages.items():
            if new.startswith('http'):
                response = self.client.get(old)
                assert response['Location'] == new
            else:
                response = self.client.get(old, follow=True)
                self.assert3xx(response, new, 302)

    def test_app_pages(self):
        self._check(
            {
                '/en-US/firefox/pages/validation': settings.VALIDATION_FAQ_URL,
            }
        )

    def test_shield_studies(self):
        pages = [
            'shield-study-2/',
            'shield_study_3',
            'shield_study_4',
            'shield_study_5',
            'shield_study_6',
            'shield_study_7',
            'shield_study_8',
            'shield_study_9',
            'shield_study_10',
            'shield_study_11',
            'shield_study_12',
            'shield_study_13',
            'shield_study_14',
            'shield_study_15',
            'shield_study_16',
            'pioneer',
        ]
        for page in pages:
            url = f'/en-US/firefox/{page}'
            self._check({url: settings.SHIELD_STUDIES_SUPPORT_URL})
