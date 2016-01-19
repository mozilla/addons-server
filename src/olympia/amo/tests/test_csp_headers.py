from django.test.utils import override_settings

from olympia.amo.tests import TestCase
from olympia.lib import settings_base as base_settings


@override_settings(CSP_REPORT_ONLY=False)
class TestCSPHeaders(TestCase):

    def test_for_specific_csp_settings(self):
        """Test that required settings are provided as headers."""
        response = self.client.get('/en-US/firefox/')
        assert response.status_code == 200
        # Make sure a default-src is locked down.
        assert "default-src 'none'" in response['content-security-policy']
        # Make sure a object-src is locked down.
        assert "object-src 'none'" in response['content-security-policy']
        # The report-uri should be set.
        assert "report-uri" in response['content-security-policy']
        # Basic assertions on the things we've defined.
        assert "script-src" in response['content-security-policy']
        assert "style-src" in response['content-security-policy']
        assert "font-src" in response['content-security-policy']
        assert "frame-src" in response['content-security-policy']

    def test_unsafe_inline_not_in_script_src(self):
        """Make sure a script-src does not have unsafe-inline."""
        assert "'unsafe-inline'" not in base_settings.CSP_SCRIPT_SRC

    def test_unsafe_eval_not_in_script_src(self):
        """Make sure a script-src does not have unsafe-eval."""
        assert "'unsafe-eval'" not in base_settings.CSP_SCRIPT_SRC

    def test_data_uri_not_in_script_src(self):
        """Make sure a script-src does not have data:."""
        assert 'data:' not in base_settings.CSP_SCRIPT_SRC

    def test_http_protocol_not_in_script_src(self):
        """Make sure a script-src does not have hosts using http:."""
        for val in base_settings.CSP_SCRIPT_SRC:
            assert not val.startswith('http:')

    def test_http_protocol_not_in_frame_src(self):
        """Make sure a frame-src does not have hosts using http:."""
        for val in base_settings.CSP_FRAME_SRC:
            assert not val.startswith('http:')

    def test_http_protocol_not_in_style_src(self):
        """Make sure a style-src does not have hosts using http:."""
        for val in base_settings.CSP_STYLE_SRC:
            assert not val.startswith('http:')

    def test_http_protocol_not_in_img_src(self):
        """Make sure a img-src does not have hosts using http:."""
        for val in base_settings.CSP_IMG_SRC:
            assert not val.startswith('http:')

    def test_prod_cdn_in_common_settings(self):
        """Make sure prod cdn is specified by default for statics."""
        prod_cdn_host = base_settings.PROD_CDN_HOST
        assert prod_cdn_host in base_settings.CSP_FONT_SRC
        assert prod_cdn_host in base_settings.CSP_IMG_SRC
        assert prod_cdn_host in base_settings.CSP_SCRIPT_SRC
        assert prod_cdn_host in base_settings.CSP_STYLE_SRC

    def test_self_in_common_settings(self):
        """Check 'self' is defined for common settings."""
        assert "'self'" in base_settings.CSP_CONNECT_SRC
        assert "'self'" in base_settings.CSP_FRAME_SRC
        assert "'self'" in base_settings.CSP_IMG_SRC
        assert "'self'" in base_settings.CSP_SCRIPT_SRC
        assert "'self'" in base_settings.CSP_STYLE_SRC

    def test_analytics_in_common_settings(self):
        """Check for anaytics hosts in img-src and script-src"""
        analytics_host = base_settings.ANALYTICS_HOST
        assert analytics_host in base_settings.CSP_IMG_SRC
        assert analytics_host in base_settings.CSP_SCRIPT_SRC

    def test_csp_settings_not_overriden_for_prod(self):
        """Checks sites/prod/settings.py doesn't have CSP_* settings.

        Because testing the import of site settings is difficult due to
        env vars, we specify prod settings in lib/base_settings and then
        override them for local-dev/-dev/stage.

        This way the default settings in lib/base_settings should represent
        what is used for prod and thus are more readily testable.

        """
        with open("sites/prod/settings.py") as f:
            data = f.read()
            assert 'CSP_' not in data
