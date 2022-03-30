import MySQLdb as mysql
import sqlalchemy.pool as pool

from services.settings import settings


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
