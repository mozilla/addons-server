import test_utils

from ..client import MockClient


class TestClient(test_utils.TestCase):

    def setUp(self):
        self.client = MockClient('services')

    def test_bad_call(self):
        with self.assertRaises(AttributeError):
            self.client.Get_Something_Nonexistent()

    def test_app_info(self):
        xml = self.client.Get_App_Info()
        assert xml.startswith('<?xml version="1.0" encoding="utf-16"?>')
        assert ' SERVICE_NAME="GET_APP_INFO"' in xml
