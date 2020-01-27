from olympia.amo.tests import (
    APITestClient,
    TestCase,
    reverse_ns,
    user_factory,
)
from olympia.constants.scanners import YARA
from olympia.scanners.models import ScannerResult
from olympia.scanners.serializers import ScannerResultSerializer


class TestScannerResultViewSet(TestCase):
    client_class = APITestClient

    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:ScannersResultsView')
        self.client.login_api(self.user)
        self.url = reverse_ns('scanner-results', api_version='v5')

    def test_endpoint_requires_authentication(self):
        self.client.logout_api()
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_endpoint_requires_permissions(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_endpoint_can_be_disabled(self):
        self.create_switch('enable-scanner-results-api', active=False)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_get(self):
        yara_result = ScannerResult.objects.create(scanner=YARA)
        self.create_switch('enable-scanner-results-api', active=True)

        response = self.client.get(self.url)

        assert response.status_code == 200
        json = response.json()
        assert 'results' in json
        results = json['results']
        assert len(results) == 1
        assert (results[0] ==
                ScannerResultSerializer(instance=yara_result).data)
