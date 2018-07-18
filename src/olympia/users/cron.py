from django.db import connections

import multidb

from celery import group

import olympia.core.logger

from olympia.amo import VALID_ADDON_STATUSES
from olympia.amo.utils import chunked

from .tasks import update_user_ratings_task


task_log = olympia.core.logger.getLogger('z.task')


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
              """ % (
        ",".join(map(str, VALID_ADDON_STATUSES))
    )

    cursor.execute(q)
    d = cursor.fetchall()
    cursor.close()

    ts = [
        update_user_ratings_task.subtask(args=[chunk])
        for chunk in chunked(d, 1000)
    ]

    group(ts).apply_async()
