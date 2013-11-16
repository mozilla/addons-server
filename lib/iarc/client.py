# -*- coding: utf8 -*-
import base64
import functools
import os

from django.conf import settings

import commonware.log
from django_statsd.clients import statsd
from suds import client as sudsclient


log = commonware.log.getLogger('z.iarc')


root = os.path.join(settings.ROOT, 'lib', 'iarc', 'wsdl', settings.IARC_ENV)
wsdl = {
    'services': 'file://' + os.path.join(root, 'iarc_services.wsdl'),
}

# Add in the whitelist of supported methods here.
services = ['Get_App_Info', 'Set_Storefront_Data', 'Get_Rating_Changes']


class Client(object):
    """
    IARC SOAP client.

    A wrapper around suds to make calls to IARC, leaving room for future WSDL
    expansion. Example usage::

        client = Client('services')
        response = client.Get_App_Info(XMLString=xml)
        print response  # response is already base64 decoded.

    """

    def __init__(self, wsdl_name):
        self.wsdl_name = wsdl_name
        self.client = None

    def __getattr__(self, attr):
        for name, methods in [('services', services)]:
            if attr in methods:
                return functools.partial(self.call, attr, wsdl=name)
        raise AttributeError('Unknown request: %s' % attr)

    def call(self, name, **data):
        log.info('IARC client call: {0} from wsdl: {1}'.format(name, wsdl))

        if self.client is None:
            self.client = sudsclient.Client(wsdl[self.wsdl_name], cache=None)

        # IARC requires messages be base64 encoded.
        for k, v in data.items():
            data[k] = base64.b64encode(v)

        with statsd.timer('mkt.iarc.request.%s' % name.lower()):
            response = getattr(self.client.service, name)(**data)

        return base64.b64decode(response)


class MockClient(Client):
    """
    Mocked IARC SOAP client.
    """

    def call(self, name, **data):
        responses = {
            'Get_App_Info': MOCK_GET_APP_INFO,
            'Set_Storefront_Data': MOCK_SET_STOREFRONT_DATA,
            'Get_Rating_Changes': MOCK_GET_RATING_CHANGES,
        }

        return responses.get(name, '')


def get_iarc_client(wsdl):
    """
    Use this to get the right client and communicate with IARC.
    """
    if settings.IARC_MOCK:
        return MockClient(wsdl)
    return Client(wsdl)


MOCK_GET_APP_INFO = '''<?xml version="1.0" encoding="utf-16"?>
<WEBSERVICE xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" SERVICE_NAME="GET_APP_INFO" TYPE="RESPONSE">
    <ROW>
        <FIELD NAME="rowId" TYPE="int" VALUE="1" />
        <FIELD NAME="submission_id" TYPE="string" VALUE="52" />
        <FIELD NAME="title" TYPE="string" VALUE="Twitter" />
        <FIELD NAME="company" TYPE="string" VALUE="Mozilla" />
        <FIELD NAME="platform" TYPE="string" VALUE="Firefox" />
        <FIELD NAME="rating_PEGI" TYPE="string" VALUE="16+" />
        <FIELD NAME="descriptors_PEGI" TYPE="string" VALUE="Language, Online" />
        <FIELD NAME="rating_USK" TYPE="string" VALUE="12+" />
        <FIELD NAME="descriptors_USK" TYPE="string" VALUE="Explizite Sprache" />
        <FIELD NAME="rating_ESRB" TYPE="string" VALUE="Mature 17+" />
        <FIELD NAME="descriptors_ESRB" TYPE="string" VALUE="Strong Language" />
        <FIELD NAME="rating_CLASSIND" TYPE="string" VALUE="14+" />
        <FIELD NAME="descriptors_CLASSIND" TYPE="string" VALUE="Cont\xc3\xa9udo Sexual, Linguagem Impr\xc3\xb3pria" />
        <FIELD NAME="rating_Generic" TYPE="string" VALUE="16+" />
        <FIELD NAME="descriptors_Generic" TYPE="string" VALUE="Language" />
        <FIELD NAME="storefront" TYPE="string" VALUE="Mozilla" />
        <FIELD NAME="interactive_elements" TYPE="string" VALUE="Shares Info, Shares Location, Social Networking, Users Interact, " />
    </ROW>
</WEBSERVICE>
'''


MOCK_SET_STOREFRONT_DATA = '''<?xml version="1.0" encoding="utf-16"?>
<WEBSERVICE xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" SERVICE_NAME="SET_STOREFRONT_DATA" TYPE="RESPONSE">
  <ROW>
    <FIELD NAME="action_status" TYPE="string" VALUE="OK - Storefront data Updated" />
    <FIELD NAME="submission_id" TYPE="string" VALUE="52" />
    <FIELD NAME="security_code" TYPE="string" VALUE="FZ32CU8" />
    <FIELD NAME="title" TYPE="string" VALUE="Twitter" />
    <FIELD NAME="company" TYPE="string" VALUE="Mozilla" />
    <FIELD NAME="rating" TYPE="string" VALUE="16+" />
    <FIELD NAME="descriptors" TYPE="string" VALUE="Language, Online" />
    <FIELD NAME="interactive_elements" TYPE="string" VALUE="Shares Info, Shares Location, Social Networking, Users Interact, " />
  </ROW>
</WEBSERVICE>
'''


MOCK_GET_RATING_CHANGES = '''<?xml version="1.0" encoding="utf-16"?>
<WEBSERVICE xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" SERVICE_NAME="GET_RATING_CHANGES" TYPE="RESPONSE">
  <ROW>
    <FIELD NAME="rowId" TYPE="int" VALUE="1" />
    <FIELD NAME="change_date" TYPE="string" VALUE="11/12/2013" />
    <FIELD NAME="submission_id" TYPE="string" VALUE="52" />
    <FIELD NAME="security_code" TYPE="string" VALUE="FZ32CU8" />
    <FIELD NAME="title" TYPE="string" VALUE="Twitter" />
    <FIELD NAME="company" TYPE="string" VALUE="Mozilla" />
    <FIELD NAME="email" TYPE="string" VALUE="nobody@mozilla.com" />
    <FIELD NAME="new_rating" TYPE="string" VALUE="18+" />
    <FIELD NAME="new_descriptors" TYPE="string" VALUE="Conteúdo Impactante, Contéudo Sexual, Drogas, Linguagem Imprópria, Nudez, Violência Extrema" />
    <FIELD NAME="rating_system" TYPE="string" VALUE="CLASSIND" />
    <FIELD NAME="change_reason" TYPE="string" VALUE="Significant issues found in special mission cut scenes." />
  </ROW>
  <ROW>
    <FIELD NAME="rowId" TYPE="int" VALUE="2" />
    <FIELD NAME="change_date" TYPE="string" VALUE="11/12/2013" />
    <FIELD NAME="submission_id" TYPE="string" VALUE="68" />
    <FIELD NAME="security_code" TYPE="string" VALUE="GZ32CU8" />
    <FIELD NAME="title" TYPE="string" VALUE="Other App" />
    <FIELD NAME="company" TYPE="string" VALUE="Mozilla" />
    <FIELD NAME="email" TYPE="string" VALUE="nobody@mozilla.com" />
    <FIELD NAME="new_rating" TYPE="string" VALUE="12+" />
    <FIELD NAME="new_descriptors" TYPE="string" VALUE="Gewalt" />
    <FIELD NAME="rating_system" TYPE="string" VALUE="USK" />
    <FIELD NAME="change_reason" TYPE="string" VALUE="Discrimination found to be within German law." />
  </ROW>
</WEBSERVICE>
'''
