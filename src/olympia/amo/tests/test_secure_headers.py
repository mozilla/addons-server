from olympia.amo.tests import TestCase


class TestSecurityHeaders(TestCase):
    def test_for_security_headers(self):
        """Test that security headers are set."""
        response = self.client.get('/en-US/firefox/')
        assert response.status_code == 200
        assert response['x-xss-protection'] == '1; mode=block'
        assert response['x-content-type-options'] == 'nosniff'
        assert response['x-frame-options'] == 'DENY'
