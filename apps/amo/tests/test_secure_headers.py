import amo.tests


class TestSecurityHeaders(amo.tests.TestCase):

    def test_for_security_headers(self):
        """Test that security headers are set."""
        response = self.client.get('/en-US/firefox/')
        assert response.status_code == 200
        assert response['x-xss-protection'] == '1; mode=block'
        assert response['x-content-type-options'] == 'nosniff'
        assert response['x-frame-options'] == 'DENY'
