import os

from django.conf import settings
from django.core.management.base import BaseCommand

import requests


root = os.path.join(settings.ROOT, 'lib', 'iarc', 'wsdl')
sources = {
    'prod': [
        ('https://www.globalratings.com/iarcprodservice/iarcservices.svc?wsdl',
         'iarc_services.wsdl'),
    ],
    'test': [
        ('https://www.globalratings.com/iarcdemoservice/iarcservices.svc?wsdl',
         'iarc_services.wsdl'),
    ]
}


class Command(BaseCommand):
    help = 'Refresh the WSDLs.'

    def handle(self, *args, **kw):
        for dir, paths in sources.items():
            for src, filename in paths:
                dest = os.path.join(root, dir, filename)
                top = os.path.dirname(dest)
                if not os.path.exists(top):
                    os.makedirs(top)
                print 'Getting', src
                open(dest, 'w').write(requests.get(src).text)
                print '...written to', dest
