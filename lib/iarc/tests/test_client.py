import test_utils

from ..client import Client, MockClient, get_iarc_client


class TestClient(test_utils.TestCase):

    def setUp(self):
        self.client = MockClient('services')

    def test_bad_call(self):
        with self.assertRaises(AttributeError):
            self.client.Get_Something_Nonexistent()

    def test_get_app_info(self):
        xml = self.client.Get_App_Info(XMLString='Proper XML here')
        assert xml.startswith('<?xml version="1.0" encoding="utf-16"?>')
        assert ' SERVICE_NAME="GET_APP_INFO"' in xml

    def test_set_storefront_data(self):
        xml = self.client.Set_Storefront_Data(XMLString='Proper XML here')
        assert xml.startswith('<?xml version="1.0" encoding="utf-16"?>')
        assert ' SERVICE_NAME="SET_STOREFRONT_DATA"' in xml

    def test_rating_changes(self):
        xml = self.client.Get_Rating_Changes(XMLString='Proper XML here')
        assert xml.startswith('<?xml version="1.0" encoding="utf-16"?>')
        assert ' SERVICE_NAME="GET_RATING_CHANGES"' in xml


class TestRightClient(test_utils.TestCase):

    def test_no_mock(self):
        with self.settings(IARC_MOCK=False):
            assert isinstance(get_iarc_client('services'), Client)

    def test_mock(self):
        with self.settings(IARC_MOCK=True):
            assert isinstance(get_iarc_client('services'), MockClient)
