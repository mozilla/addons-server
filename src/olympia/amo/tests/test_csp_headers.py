import os

from django.conf import settings
from django.test.utils import override_settings
from django.urls import reverse

from olympia.amo.tests import TestCase, user_factory
from olympia.lib import settings_base as base_settings


def test_default_settings_no_report_only():
    assert getattr(settings, 'CONTENT_SECURITY_POLICY', {}).keys()


class TestCSPHeaders(TestCase):
    @override_settings(SITE_URL='http://internal-admin-testserver')
    def test_admin_csp(self):
        user = user_factory(email='me@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        url = reverse('admin:index')
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        self._test_for_specific_csp_settings(response)
        # Extra for the admin
        expected = [
            'script-src',
            *settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src'],
            'http://internal-admin-testserver/en-US/admin/models/jsi18n/',
        ]
        assert ' '.join(expected) + ';' in response['content-security-policy']

    def test_admin_csp_different_locale(self):
        user = user_factory(email='me@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        with self.activate('fr'):
            url = reverse('admin:index')
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        self._test_for_specific_csp_settings(response)
        # Extra for the admin
        expected = [
            'script-src',
            *settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src'],
            'http://testserver/fr/admin/models/jsi18n/',
        ]
        assert ' '.join(expected) + ';' in response['content-security-policy']

    def test_developers_csp(self):
        response = self.client.get('/en-US/developers/')
        assert response.status_code == 200
        self._test_for_specific_csp_settings(response)
        expected = [
            'script-src',
            *settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src'],
        ]
        assert ' '.join(expected) + ';' in response['content-security-policy']

    def _test_for_specific_csp_settings(self, response):
        """Test that required settings are provided as headers."""
        # Make sure a default-src is set.
        assert "default-src 'none'" in response['content-security-policy']
        # Make sure a object-src is locked down.
        assert "object-src 'none'" in response['content-security-policy']
        # The report-uri should be set.
        assert 'report-uri' in response['content-security-policy']
        # Basic assertions on the things we've defined.
        assert 'script-src' in response['content-security-policy']
        assert 'style-src' in response['content-security-policy']
        assert 'font-src' in response['content-security-policy']
        assert 'form-action' in response['content-security-policy']
        assert 'frame-src' in response['content-security-policy']
        assert 'child-src' in response['content-security-policy']
        # Some things we don't use and are not defining on purpose.
        assert 'base-uri' not in response['content-security-policy']

    def test_unsafe_inline_not_in_script_src(self):
        """Make sure a script-src does not have unsafe-inline."""
        assert (
            "'unsafe-inline'"
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src']
        )

    def test_unsafe_eval_not_in_script_src(self):
        """Make sure a script-src does not have unsafe-eval."""
        assert (
            "'unsafe-eval'"
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src']
        )

    def test_data_and_blob_not_in_script_and_style_src(self):
        """Make sure a script-src/style-src does not have data: or blob:."""
        assert (
            'blob:'
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src']
        )
        assert (
            'data:'
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src']
        )
        assert (
            'blob:'
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['style-src']
        )
        assert (
            'data:'
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['style-src']
        )

    def test_http_protocol_not_in_script_src(self):
        """Make sure a script-src does not have hosts using http:."""
        for val in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src']:
            assert not val.startswith('http:')

    def test_http_protocol_not_in_frame_src(self):
        """Make sure a frame-src does not have hosts using http:."""
        for val in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['frame-src']:
            assert not val.startswith('http:')

    def test_http_protocol_not_in_child_src(self):
        """Make sure a child-src does not have hosts using http:."""
        for val in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['child-src']:
            assert not val.startswith('http:')

    def test_http_protocol_not_in_style_src(self):
        """Make sure a style-src does not have hosts using http:."""
        for val in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['style-src']:
            assert not val.startswith('http:')

    def test_http_protocol_not_in_img_src(self):
        """Make sure a img-src does not have hosts using http:."""
        for val in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['img-src']:
            assert not val.startswith('http:')

    def test_blob_and_data_in_img_src(self):
        """Test that img-src contains data/blob."""
        assert 'blob:' in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['img-src']
        assert 'data:' in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['img-src']

    def test_child_src_matches_frame_src(self):
        """Check frame-src directive has same settings as child-src"""
        assert (
            base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['frame-src']
            == base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['child-src']
        )

    def test_prod_static_url_in_common_settings(self):
        """Make sure prod cdn is specified by default for statics."""
        prod_static_url = base_settings.PROD_STATIC_URL
        assert (
            prod_static_url
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['font-src']
        )
        assert (
            prod_static_url
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['img-src']
        )
        assert (
            prod_static_url
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src']
        )
        assert (
            prod_static_url
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['style-src']
        )

        prod_media_url = base_settings.PROD_MEDIA_URL
        assert (
            prod_media_url
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['font-src']
        )
        assert (
            prod_media_url
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['img-src']
        )
        assert (
            prod_media_url
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src']
        )
        assert (
            prod_media_url
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['style-src']
        )

    def test_self_in_common_settings(self):
        """Check 'self' is defined for common settings."""
        assert (
            "'self'"
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['connect-src']
        )
        assert (
            "'self'" in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['img-src']
        )
        assert (
            "'self'"
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['form-action']
        )

    def test_not_self_in_script_child_or_style_src(self):
        """script-src/style-src/child-src should not need 'self' or the entire
        a.m.o. domain"""
        assert (
            "'self'"
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src']
        )
        assert (
            'https://addons.mozilla.org'
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src']
        )
        assert (
            "'self'"
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['style-src']
        )
        assert (
            'https://addons.mozilla.org'
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['style-src']
        )
        assert (
            "'self'"
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['child-src']
        )
        assert (
            'https://addons.mozilla.org'
            not in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['child-src']
        )

    def test_analytics_in_common_settings(self):
        """Check for anaytics hosts in connect-src, img-src and script-src"""
        # See https://github.com/mozilla/addons/issues/14799#issuecomment-2127359422
        assert (
            base_settings.GOOGLE_ANALYTICS_HOST
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['connect-src']
        )
        assert (
            base_settings.GOOGLE_TAGMANAGER_HOST
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['connect-src']
        )
        assert (
            base_settings.GOOGLE_ADDITIONAL_ANALYTICS_HOST
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['connect-src']
        )

        assert (
            base_settings.GOOGLE_ANALYTICS_HOST
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['img-src']
        )
        assert (
            base_settings.GOOGLE_TAGMANAGER_HOST
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['img-src']
        )

        assert (
            base_settings.GOOGLE_ANALYTICS_HOST
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src']
        )
        assert (
            base_settings.GOOGLE_TAGMANAGER_HOST
            in base_settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src']
        )

    def test_csp_settings_not_overriden_for_prod(self):
        """Checks sites/prod/settings.py doesn't change CONTENT_SECURITY_POLICY
        settings.

        Because testing the import of site settings is difficult due to
        env vars, we specify prod settings in lib/base_settings and then
        override them for local-dev/-dev/stage.

        This way the default settings in lib/base_settings should represent
        what is used for prod and thus are more readily testable.

        """
        path = os.path.join(
            settings.ROOT, 'src', 'olympia', 'conf', 'prod', 'settings.py'
        )

        with open(path) as f:
            data = f.read()
            assert 'CONTENT_SECURITY_POLICY' not in data
