from django.db import connections

import commonware.log
import multidb
from celery.messaging import establish_connection
from celeryutils import task

import cronjobs
from amo import VALID_STATUSES
from amo.utils import chunked
from .models import UserProfile

task_log = commonware.log.getLogger('z.task')


@cronjobs.register
def update_user_ratings():
    """Update add-on author's ratings."""

    cursor = connections[multidb.get_slave()].cursor()
    # We build this query ahead of time because the cursor complains about data
    # truncation if it does the parameters.  Also, this query is surprisingly
    # quick, <1sec for 6100 rows returned
    q = """   SELECT
                addons_users.user_id as user_id,
                AVG(rating) as avg_rating
              FROM reviews
                INNER JOIN versions
                INNER JOIN addons_users
                INNER JOIN addons
              ON reviews.version_id = versions.id
                AND addons.id = versions.addon_id
                AND addons_users.addon_id = addons.id
              WHERE reviews.reply_to IS NULL
                AND reviews.rating > 0
                AND addons.status IN (%s)
              GROUP BY addons_users.user_id
              """ % (",".join(map(str, VALID_STATUSES)))

    cursor.execute(q)
    d = cursor.fetchall()
    cursor.close()

    with establish_connection() as conn:
        for chunk in chunked(d, 1000):
            _update_user_ratings.apply_async(args=[chunk],
                                                  connection=conn)


@task(rate_limit='15/m')
def _update_user_ratings(data, **kw):
    task_log.info("[%s@%s] Updating add-on author's ratings." %
                   (len(data), _update_user_ratings.rate_limit))
    for pk, rating in data:
        rating = "%.2f" % round(rating, 2)
        UserProfile.objects.filter(pk=pk).update(averagerating=rating)
