import datetime
import hashlib
import json
import logging
import os
import subprocess
from collections import defaultdict

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.forms import ValidationError
from django.template import Context, loader

from celery.exceptions import RetryTaskError
from celeryutils import task
from pyelasticsearch.exceptions import ElasticHttpNotFoundError
from test_utils import RequestFactory

import amo
from amo.decorators import write
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import chunked, JSONEncoder
from editors.models import RereviewQueue
from files.models import FileUpload
from files.utils import WebAppParser
from lib.es.utils import get_indices
from users.utils import get_task_user

from mkt.constants.regions import WORLDWIDE
from mkt.developers.tasks import _fetch_manifest, run_validator, validator
from mkt.webapps.models import Webapp, WebappIndexer
from mkt.webapps.utils import get_locale_properties

task_log = logging.getLogger('z.task')


@task(rate_limit='15/m')
def webapp_update_weekly_downloads(data, **kw):
    task_log.info('[%s@%s] Update weekly downloads.' % (
        len(data), webapp_update_weekly_downloads.rate_limit))

    for line in data:
        webapp = Webapp.objects.get(pk=line['addon'])
        webapp.update(weekly_downloads=line['count'])


def _get_content_hash(content):
    return 'sha256:%s' % hashlib.sha256(content).hexdigest()


def _log(webapp, message, rereview=False, exc_info=False):
    if rereview:
        message = u'(Re-review) ' + unicode(message)
    task_log.info(u'[Webapp:%s] %s' % (webapp, unicode(message)),
                  exc_info=exc_info)


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
    retry_secs = 3600
    task_log.info('[%s@%s] Update manifests.' %
                  (len(ids), update_manifests.rate_limit))
    check_hash = kw.pop('check_hash', True)
    retries = kw.pop('retries', {})
    # Since we'll be logging the updated manifest change to the users log,
    # we'll need to log in as user.
    amo.set_user(get_task_user())

    for id in ids:
        _update_manifest(id, check_hash, retries)
    if retries:
        try:
            update_manifests.retry(args=(retries.keys(),),
                                   kwargs={'check_hash': check_hash,
                                           'retries': retries},
                                   eta=datetime.datetime.now() +
                                       datetime.timedelta(seconds=retry_secs),
                                   max_retries=4)
        except RetryTaskError:
            _log(id, 'Retrying task in %d seconds.' % retry_secs)

    return retries


def _update_manifest(id, check_hash, failed_fetches):
    webapp = Webapp.objects.get(pk=id)
    version = webapp.versions.latest()
    file_ = version.files.latest()

    _log(webapp, u'Fetching webapp manifest')
    if not file_:
        _log(webapp, u'Ignoring, no existing file')
        return

    # Fetch manifest, catching and logging any exception.
    try:
        content = _fetch_manifest(webapp.manifest_url)
    except Exception, e:
        msg = u'Failed to get manifest from %s. Error: %s' % (
            webapp.manifest_url, e)
        failed_fetches[id] = failed_fetches.get(id, 0) + 1
        if failed_fetches[id] >= 3:
            _log(webapp, msg, rereview=True, exc_info=True)
            if webapp.status in amo.WEBAPPS_APPROVED_STATUSES:
                RereviewQueue.flag(webapp, amo.LOG.REREVIEW_MANIFEST_CHANGE,
                                   msg)
            del failed_fetches[id]
        else:
            _log(webapp, msg, rereview=False, exc_info=True)
        return

    # Check hash.
    if check_hash:
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
            if webapp.status in amo.WEBAPPS_APPROVED_STATUSES:
                RereviewQueue.flag(webapp, amo.LOG.REREVIEW_MANIFEST_CHANGE,
                                   msg)
            return
    else:
        _log(webapp,
             u'Validation for upload UUID %s has no result' % upload.uuid)

    # Get the old manifest before we overwrite it.
    new = json.loads(content)
    old = _open_manifest(webapp, file_)

    # New manifest is different and validates, update version/file.
    try:
        webapp.manifest_updated(content, upload)
    except:
        _log(webapp, u'Failed to create version', exc_info=True)

    # Check for any name changes at root and in locales. If any were added or
    # updated, send to re-review queue.
    msg = []
    rereview = False

    if old and old.get('name') != new.get('name'):
        rereview = True
        msg.append(u'Manifest name changed from "%s" to "%s".' % (
            old.get('name'), new.get('name')))

    new_version = webapp.versions.latest()
    # Compare developer_name between old and new version using the property that
    # fallbacks to the author name instead of using the db field directly. This
    # allows us to avoid forcing a re-review on old apps which didn't have
    # developer name in their manifest initially and upload a new version that
    # does, providing that it matches the original author name.
    if version.developer_name != new_version.developer_name:
        rereview = True
        msg.append(u'Developer name changed from "%s" to "%s".'
            % (version.developer_name, new_version.developer_name))

    # Get names in "locales" as {locale: name}.
    locale_names = get_locale_properties(new, 'name', webapp.default_locale)

    # Check changes to default_locale.
    locale_changed = webapp.update_default_locale(new.get('default_locale'))
    if locale_changed:
        msg.append(u'Default locale changed from "%s" to "%s".'
                   % locale_changed)

    # Update names
    crud = webapp.update_names(locale_names)
    if any(crud.values()):
        webapp.save()

    if crud.get('added'):
        rereview = True
        msg.append(u'Locales added: %s' % crud.get('added'))
    if crud.get('updated'):
        rereview = True
        msg.append(u'Locales updated: %s' % crud.get('updated'))

    # Check if supported_locales changed and update if so.
    webapp.update_supported_locales(new)

    if rereview:
        msg = ' '.join(msg)
        _log(webapp, msg, rereview=True)
        if webapp.status in amo.WEBAPPS_APPROVED_STATUSES:
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


@task
@write
def add_uuids(ids, **kw):
    for chunk in chunked(ids, 50):
        for app in Webapp.objects.filter(id__in=chunk):
            # Save triggers the creation of a guid if the app doesn't currently
            # have one.
            app.save()


@task
@write
def update_supported_locales(ids, **kw):
    """
    Task intended to run via command line to update all apps' supported locales
    based on the current version.
    """
    for chunk in chunked(ids, 50):
        for app in Webapp.objects.filter(id__in=chunk):
            try:
                if app.update_supported_locales():
                    _log(app, u'Updated supported locales')
            except Exception:
                _log(app, u'Updating supported locales failed.', exc_info=True)


@task(acks_late=True)
@write
def index_webapps(ids, **kw):
    task_log.info('Indexing apps %s-%s. [%s]' % (ids[0], ids[-1], len(ids)))

    index = kw.pop('index', WebappIndexer.get_index())
    # Note: If reindexing is currently occurring, `get_indices` will return
    # more than one index.
    indices = get_indices(index)

    es = WebappIndexer.get_es(urls=settings.ES_URLS)
    qs = Webapp.indexing_transformer(Webapp.uncached.filter(id__in=ids))
    for obj in qs:
        doc = WebappIndexer.extract_document(obj.id, obj)
        for idx in indices:
            WebappIndexer.index(doc, id_=obj.id, es=es, index=idx)


@task(acks_late=True)
@write
def unindex_webapps(ids, **kw):
    task_log.info('Un-indexing apps %s-%s. [%s]' % (ids[0], ids[-1], len(ids)))

    index = kw.pop('index', WebappIndexer.get_index())
    # Note: If reindexing is currently occurring, `get_indices` will return
    # more than one index.
    indices = get_indices(index)

    es = WebappIndexer.get_es(urls=settings.ES_URLS)
    for id_ in ids:
        for idx in indices:
            try:
                WebappIndexer.unindex(id_=id_, es=es, index=idx)
            except ElasticHttpNotFoundError:
                # Ignore if it's not there.
                task_log.info(
                    u'[Webapp:%s] Unindexing app but not found in index' % id_)


@task
def dump_app(id, **kw):
    # Because @robhudson told me to.
    from mkt.api.resources import AppResource
    # Note: not using storage because all these operations should be local.
    target_dir = os.path.join(settings.DUMPED_APPS_PATH, 'apps',
                              str(id / 1000))
    target_file = os.path.join(target_dir, str(id) + '.json')

    try:
        obj = Webapp.objects.get(pk=id)
    except Webapp.DoesNotExist:
        task_log.info(u'Webapp does not exist: {0}'.format(id))
        return

    req = RequestFactory().get('/')
    req.REGION = WORLDWIDE

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    task_log.info('Dumping app {0} to {1}'.format(id, target_file))
    res = AppResource().dehydrate_objects([obj], request=req)
    json.dump(res[0], open(target_file, 'w'), cls=JSONEncoder)
    return target_file


@task
def dump_apps(ids, **kw):
    task_log.info(u'Dumping apps {0} to {0}. [{0}]'
                  .format(ids[0], ids[-1], len(ids)))
    for id in ids:
        dump_app(id)


@task
def zip_apps(*args, **kw):
    # Note: not using storage because all these operations should be local.
    today = datetime.datetime.today().strftime('%Y-%m-%d')
    target_dir = os.path.join(settings.DUMPED_APPS_PATH, 'tarballs')
    target_file = os.path.join(target_dir, today + '.tgz')

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    # Put some .txt files in place.
    context = Context({'date': today, 'url': settings.SITE_URL})
    files = ['license.txt', 'readme.txt']
    for f in files:
        template = loader.get_template('webapps/dump/' + f)
        dest = os.path.join(settings.DUMPED_APPS_PATH, f)
        open(dest, 'w').write(template.render(context))

    cmd = ['tar', 'czf', target_file, '-C',
           settings.DUMPED_APPS_PATH, 'apps'] + files
    task_log.info(u'Creating app dump {0}'.format(target_file))
    subprocess.call(cmd)
    return target_file


def _update_features(id):
    try:
        webapp = Webapp.objects.get(pk=id)
    except Webapp.DoesNotExist:
        _log(id, u'Webapp does not exist')
        return

    # We only detect features on packaged webapps.
    if not webapp.is_packaged:
        _log(id, u'Webapp is not a packaged app')
        return

    # If the app doesn't have a current_version, don't bother either.
    if not webapp.current_version:
        _log(id, u'Webapp does not have a current_version')
        return

    # If the app already has a non-empty feature profile, don't touch it.
    features = webapp.current_version.features
    if features.to_list():
        _log(id, u'Webapp already has a non-empty feature profile')
        return

    version = webapp.current_version
    res = run_validator(version.all_files[0].file_path)
    validation_result = json.loads(res)

    # Set all detected features as True and save them.
    feature_profile = validation_result['feature_profile']
    keys = ['has_%s' % feature.lower() for feature in feature_profile]
    data = defaultdict.fromkeys(keys, True)

    # Update features.
    features.update(**data)


@task
def update_features(ids, **kw):
    for id in ids:
        _update_features(id)


def _update_developer_name(id):
    try:
        webapp = Webapp.objects.get(pk=id)
    except Webapp.DoesNotExist:
        _log(id, u'Webapp does not exist')
        return

    version = webapp.current_version

    # If the app doesn't have a current_version, don't bother.
    if not version:
        _log(id, u'Webapp does not have a current_version')
        return

    # If the current_version already has a non-empty developer_name set, don't
    # touch it and bail.
    if version._developer_name:
        _log(id, u'Webapp already has a non-empty developer_name')
        return

    try:
        data = WebAppParser().parse(webapp.get_latest_file().file_path)
    except ValidationError:
        _log(id, u'Webapp manifest can not be parsed')
        return

    max_len = version._meta.get_field_by_name('_developer_name')[0].max_length
    version.update(_developer_name=data['developer_name'][:max_len])


@task
def update_developer_name(ids, **kw):
    for id in ids:
        _update_developer_name(id)
