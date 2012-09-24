import hashlib
import json
import logging

from celeryutils import task

from django.core.files.storage import default_storage as storage

import amo
from amo.decorators import write
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from editors.models import RereviewQueue
from files.models import FileUpload
from mkt.developers.tasks import _fetch_manifest, validator
from mkt.webapps.models import Webapp
from users.utils import get_task_user

task_log = logging.getLogger('z.task')


@task(rate_limit='15/m')
def webapp_update_weekly_downloads(data, **kw):
    task_log.info('[%s@%s] Update weekly downloads.' %
                   (len(data), webapp_update_weekly_downloads.rate_limit))

    for line in data:
        webapp = Webapp.objects.get(pk=line['addon'])
        webapp.update(weekly_downloads=line['count'])


def _get_content_hash(content):
    return 'sha256:%s' % hashlib.sha256(content).hexdigest()


def _log(webapp, message, rereview=False, exc_info=False):
    if rereview:
        message = u'(Re-review) ' + message
    task_log.info(u'[Webapp:%s] %s' % (webapp, message), exc_info=exc_info)


def _open_manifest(webapp, file_):
    try:
        if file_.status == amo.STATUS_DISABLED:
            path = file_.guarded_file_path
        else:
            path = file_.file_path
        with storage.open(path, 'r') as fh:
            manifest_json = fh.read()
        return json.loads(manifest_json)
    except IOError:
        _log(webapp, u'Original manifest could not be found at: %s' % path,
             exc_info=True)
    except ValueError:
        _log(webapp, u'JSON decoding error', exc_info=True)


@task
@write
def update_manifests(ids, **kw):
    task_log.info('[%s@%s] Update manifests.' %
                  (len(ids), update_manifests.rate_limit))

    # Since we'll be logging the updated manifest change to the users log,
    # we'll need to log in as user.
    amo.set_user(get_task_user())

    for id in ids:
        _update_manifest(id)


def _update_manifest(id):
    webapp = Webapp.objects.get(pk=id)
    file_ = webapp.get_latest_file()

    _log(webapp, u'Fetching webapp manifest')
    if not file_:
        _log(webapp, u'Ignoring, no existing file')
        return

    # Fetch manifest, catching and logging any exception.
    try:
        content = _fetch_manifest(webapp.manifest_url)
    except Exception, e:
        msg = u'Failed to get manifest from %s. Error: %s' % (
            webapp.manifest_url, e.message)
        _log(webapp, msg, rereview=True, exc_info=True)
        RereviewQueue.flag(webapp, amo.LOG.REREVIEW_MANIFEST_CHANGE, msg)
        return

    # Check hash.
    hash_ = _get_content_hash(content)
    if file_.hash == hash_:
        _log(webapp, u'Manifest the same')
        return

    _log(webapp, u'Manifest different')

    # Validate the new manifest.
    upload = FileUpload.objects.create()
    upload.add_file([content], webapp.manifest_url, len(content),
                    is_webapp=True)
    validator(upload.pk)
    upload = FileUpload.uncached.get(pk=upload.pk)
    if upload.validation:
        v8n = json.loads(upload.validation)
        if v8n['errors']:
            v8n_url = absolutify(reverse(
                'mkt.developers.upload_detail', args=[upload.uuid]))
            msg = u'Validation errors:\n'
            for m in v8n['messages']:
                if m['type'] == u'error':
                    msg += u'* %s\n' % m['message']
            msg += u'\nValidation Result:\n%s' % v8n_url
            _log(webapp, msg, rereview=True)
            RereviewQueue.flag(webapp, amo.LOG.REREVIEW_MANIFEST_CHANGE, msg)
            return
    else:
        _log(webapp,
             u'Validation for upload UUID %s has no result' % upload.uuid)

    # Get the old manifest before we overwrite it.
    new = json.loads(content)
    old = _open_manifest(webapp, file_)

    # New manifest is different and validates, create a new version.
    try:
        webapp.manifest_updated(content, upload)
    except:
        _log(webapp, u'Failed to create version', exc_info=True)

    # Check for any name changes for re-review.
    if (old and old.get('name') and old.get('name') != new.get('name')):
        msg = u'Manifest name changed from "%s" to "%s"' % (
            old.get('name'), new.get('name'))
        _log(webapp, msg, rereview=True)
        RereviewQueue.flag(webapp, amo.LOG.REREVIEW_MANIFEST_CHANGE, msg)


@task
def update_cached_manifests(id, **kw):
    try:
        webapp = Webapp.objects.get(pk=id)
    except Webapp.DoesNotExist:
        _log(id, u'Webapp does not exist')
        return

    if not webapp.is_packaged:
        return

    # Rebuilds the packaged app mini manifest and stores it in cache.
    webapp.get_cached_manifest(force=True)
    _log(webapp, u'Updated cached mini manifest')
