from django.db import connections

import commonware.log
import multidb
from celery.task.sets import TaskSet

import cronjobs
from amo import VALID_STATUSES
from amo.utils import chunked
from .models import UserProfile
from .tasks import update_user_ratings_task

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

    ts = [update_user_ratings_task.subtask(args=[chunk])
          for chunk in chunked(d, 1000)]
    TaskSet(ts).apply_async()


@cronjobs.register
def reindex_users(index=None):
    from . import tasks
    ids = UserProfile.objects.values_list('id', flat=True)
    taskset = [tasks.index_users.subtask(args=[chunk], kwargs=dict(index=index))
               for chunk in chunked(sorted(list(ids)), 150)]
    TaskSet(taskset).apply_async()
