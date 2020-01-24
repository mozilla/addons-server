from olympia.amo.tests import TestCase
from olympia.constants.scanners import CUSTOMS
from olympia.scanners.models import ScannerResult
from olympia.scanners.serializers import ScannerResultSerializer


class TestScannerResultSerializer(TestCase):
    def test_serialize(self):
        result = ScannerResult.objects.create(scanner=CUSTOMS)
        data = ScannerResultSerializer(instance=result).data
        assert data == {
            'id': result.id,
            'scanner': result.get_scanner_name(),
            'results': result.results,
        }
