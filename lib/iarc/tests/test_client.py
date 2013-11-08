import test_utils

from ..client import Client, MockClient, get_iarc_client


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


class TestRightClient(test_utils.TestCase):

    def test_no_mock(self):
        with self.settings(IARC_MOCK=False):
            assert isinstance(get_iarc_client('services'), Client)

    def test_mock(self):
        with self.settings(IARC_MOCK=True):
            assert isinstance(get_iarc_client('services'), MockClient)
