import os

from django.conf import settings
from django.test.utils import override_settings

from olympia.amo.tests import TestCase
from olympia.lib import settings_base as base_settings


def test_default_settings_no_report_only():
    assert settings.CSP_REPORT_ONLY is False


@override_settings(CSP_REPORT_ONLY=False)
class TestCSPHeaders(TestCase):
    def test_for_specific_csp_settings(self):
        """Test that required settings are provided as headers."""
        response = self.client.get('/en-US/developers/')
        assert response.status_code == 200
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
        assert "'unsafe-inline'" not in base_settings.CSP_SCRIPT_SRC

    def test_unsafe_eval_not_in_script_src(self):
        """Make sure a script-src does not have unsafe-eval."""
        assert "'unsafe-eval'" not in base_settings.CSP_SCRIPT_SRC

    def test_data_and_blob_not_in_script_and_style_src(self):
        """Make sure a script-src/style-src does not have data: or blob:."""
        assert 'blob:' not in base_settings.CSP_SCRIPT_SRC
        assert 'data:' not in base_settings.CSP_SCRIPT_SRC
        assert 'blob:' not in base_settings.CSP_STYLE_SRC
        assert 'data:' not in base_settings.CSP_STYLE_SRC

    def test_http_protocol_not_in_script_src(self):
        """Make sure a script-src does not have hosts using http:."""
        for val in base_settings.CSP_SCRIPT_SRC:
            assert not val.startswith('http:')

    def test_http_protocol_not_in_frame_src(self):
        """Make sure a frame-src does not have hosts using http:."""
        for val in base_settings.CSP_FRAME_SRC:
            assert not val.startswith('http:')

    def test_http_protocol_not_in_child_src(self):
        """Make sure a child-src does not have hosts using http:."""
        for val in base_settings.CSP_CHILD_SRC:
            assert not val.startswith('http:')

    def test_http_protocol_not_in_style_src(self):
        """Make sure a style-src does not have hosts using http:."""
        for val in base_settings.CSP_STYLE_SRC:
            assert not val.startswith('http:')

    def test_http_protocol_not_in_img_src(self):
        """Make sure a img-src does not have hosts using http:."""
        for val in base_settings.CSP_IMG_SRC:
            assert not val.startswith('http:')

    def test_blob_and_data_in_img_src(self):
        """Test that img-src contains data/blob."""
        assert 'blob:' in base_settings.CSP_IMG_SRC
        assert 'data:' in base_settings.CSP_IMG_SRC

    def test_child_src_matches_frame_src(self):
        """Check frame-src directive has same settings as child-src"""
        assert base_settings.CSP_FRAME_SRC == base_settings.CSP_CHILD_SRC

    def test_prod_static_url_in_common_settings(self):
        """Make sure prod cdn is specified by default for statics."""
        prod_static_url = base_settings.PROD_STATIC_URL
        assert prod_static_url in base_settings.CSP_FONT_SRC
        assert prod_static_url in base_settings.CSP_IMG_SRC
        assert prod_static_url in base_settings.CSP_SCRIPT_SRC
        assert prod_static_url in base_settings.CSP_STYLE_SRC

        prod_media_url = base_settings.PROD_MEDIA_URL
        assert prod_media_url not in base_settings.CSP_FONT_SRC
        assert prod_media_url in base_settings.CSP_IMG_SRC
        assert prod_media_url not in base_settings.CSP_SCRIPT_SRC
        assert prod_media_url not in base_settings.CSP_STYLE_SRC

    def test_self_in_common_settings(self):
        """Check 'self' is defined for common settings."""
        assert "'self'" in base_settings.CSP_CONNECT_SRC
        assert "'self'" in base_settings.CSP_IMG_SRC
        assert "'self'" in base_settings.CSP_FORM_ACTION

    def test_not_self_in_script_child_or_style_src(self):
        """script-src/style-src/child-src should not need 'self' or the entire
        a.m.o. domain"""
        assert "'self'" not in base_settings.CSP_SCRIPT_SRC
        assert 'https://addons.mozilla.org' not in base_settings.CSP_SCRIPT_SRC
        assert "'self'" not in base_settings.CSP_STYLE_SRC
        assert 'https://addons.mozilla.org' not in base_settings.CSP_STYLE_SRC
        assert "'self'" not in base_settings.CSP_CHILD_SRC
        assert 'https://addons.mozilla.org' not in base_settings.CSP_CHILD_SRC

    def test_analytics_in_common_settings(self):
        """Check for anaytics hosts in connect-src, img-src and script-src"""
        # See https://github.com/mozilla/addons/issues/14799#issuecomment-2127359422
        assert base_settings.GOOGLE_ANALYTICS_HOST in base_settings.CSP_CONNECT_SRC
        assert base_settings.GOOGLE_TAGMANAGER_HOST in base_settings.CSP_CONNECT_SRC
        assert (
            base_settings.GOOGLE_ADDITIONAL_ANALYTICS_HOST
            in base_settings.CSP_CONNECT_SRC
        )

        assert base_settings.GOOGLE_ANALYTICS_HOST in base_settings.CSP_IMG_SRC
        assert base_settings.GOOGLE_TAGMANAGER_HOST in base_settings.CSP_IMG_SRC

        assert base_settings.GOOGLE_ANALYTICS_HOST in base_settings.CSP_SCRIPT_SRC
        assert base_settings.GOOGLE_TAGMANAGER_HOST in base_settings.CSP_SCRIPT_SRC

    def test_csp_settings_not_overriden_for_prod(self):
        """Checks sites/prod/settings.py doesn't have CSP_* settings.

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
            assert 'CSP_' not in data
