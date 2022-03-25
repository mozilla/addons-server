import logging
import logging.config

import MySQLdb as mysql
import sqlalchemy.pool as pool

from services.settings import settings

import olympia.core.logger


def getconn():
    db = settings.SERVICES_DATABASE
    return mysql.connect(
        host=db['HOST'],
        user=db['USER'],
        passwd=db['PASSWORD'],
        db=db['NAME'],
        charset=db['OPTIONS']['charset'],
    )


mypool = pool.QueuePool(getconn, max_overflow=10, pool_size=5, recycle=300)


def log_configure():
    """You have to call this to explicitly configure logging."""
    cfg = {
        'version': 1,
        'filters': {},
        'handlers': {
            'mozlog': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
                'formatter': 'json',
            },
        },
        'formatters': {
            'json': {
                '()': olympia.core.logger.JsonFormatter,
                'logger_name': 'http_app_addons',
            },
        },
    }
    logging.config.dictConfig(cfg)
