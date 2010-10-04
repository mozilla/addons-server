"""
Email sharing of add-ons and collections with various services.
"""
from . import models


SERVICES_LIST = (models.DIGG, models.FACEBOOK, models.DELICIOUS,
                 models.MYSPACE, models.FRIENDFEED, models.TWITTER)
SERVICES = dict((service.shortname, service) for service in SERVICES_LIST)
