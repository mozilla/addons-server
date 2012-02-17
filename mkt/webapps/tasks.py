import hashlib
import logging
from tempfile import mkstemp

from celeryutils import task

from amo import set_user
from amo.utils import rm_local_tmp_file
from devhub.tasks import _fetch_content
from files.utils import get_sha256
from users.utils import get_task_user
from mkt.webapps.models import Webapp

task_log = logging.getLogger('z.task')


@task(rate_limit='15/m')
def webapp_update_weekly_downloads(data, **kw):
    task_log.info('[%s@%s] Update weekly downloads.' %
                   (len(data), webapp_update_weekly_downloads.rate_limit))

    for line in data:
        webapp = Webapp.objects.get(pk=line['addon'])
        webapp.update(weekly_downloads=line['count'])


def _get_content_hash(temp, url):
    # Fetch the webapp, write it to a file and return the hash of that.
    data = _fetch_content(url).read()
    with open(temp, 'w') as fp:
        fp.write(data)
    return 'sha256:%s' % get_sha256(temp)


@task
def update_manifests(ids, **kw):
    task_log.info('[%s@%s] Update manifests.' %
                  (len(ids), update_manifests.rate_limit))

    # Since we'll be logging the updated manifest change to the users log,
    # we'll need to log in as user.
    set_user(get_task_user())

    for id in ids:
        task_log.info('Fetching webapp manifest for: %s' % id)

        webapp = Webapp.objects.get(pk=id)
        file_ = webapp.get_latest_file()
        if not file_:
            task_log.info('Ignoring, no existing file for: %s' % id)
            continue

        # Fetch the data.
        temp = mkstemp(suffix='.webapp')[1]
        try:
            hash_ = _get_content_hash(temp, webapp.manifest_url)
        except:
            task_log.info('Failed to get manifest for: %s' % id,
                          exc_info=True)
            rm_local_tmp_file(temp)
            continue

        # Try to create a new version, if needed.
        try:
            if file_.hash != hash_:
                task_log.info('Webapp manifest different for: %s' % id)
                webapp.manifest_updated(temp)
            else:
                task_log.info('Webapp manifest the same for: %s' % id)
        except:
            task_log.info('Failed to create version for: %s' % id,
                          exc_info=True)
        finally:
            rm_local_tmp_file(temp)
