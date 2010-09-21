import logging

from django.conf import settings

import mongoengine
import pymongo

log = logging.getLogger('z.mongo')

def connect_mongo():
    """Returns a Database object on success, False on failure."""
    try:
        db = mongoengine.connect(settings.MONGO_DATABASE,
                                 host=settings.MONGO_HOST,
                                 port=settings.MONGO_PORT,
                                 username=settings.MONGO_USERNAME,
                                 password=settings.MONGO_PASSWORD,
                                 network_timeout=0.1)
    except pymongo.errors.AutoReconnect, e:
        log.warn('Failed to connect to mongodb, will reconnect (%s): %s' %
                 (settings.MONGO_DATABASE, e))
    except Exception, e:
        log.critical('Failed to connect to mongodb (%s): %s' %
                 (settings.MONGO_DATABASE, e))
        return False
    return db
