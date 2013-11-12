import datetime
import hashlib
import json
import logging
import os
import shutil
import subprocess
import time

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.files.storage import default_storage as storage
from django.template import Context, loader

from celery.exceptions import RetryTaskError
from celeryutils import task
from pyelasticsearch.exceptions import ElasticHttpNotFoundError
from test_utils import RequestFactory
from tower import ugettext as _

import amo
from amo.decorators import write
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import chunked, JSONEncoder, send_mail_jinja
from editors.models import RereviewQueue
from files.models import FileUpload
from files.utils import WebAppParser
from lib.es.utils import get_indices
from lib.metrics import get_monolith_client
from users.utils import get_task_user

import mkt
from mkt.constants.regions import WORLDWIDE
from mkt.developers.tasks import fetch_icon, _fetch_manifest, validator
from mkt.webapps.models import AppManifest, Webapp, WebappIndexer
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
                                   max_retries=5)
        except RetryTaskError:
            _log(id, 'Retrying task in %d seconds.' % retry_secs)

    return retries


def notify_developers_of_failure(app, error_message, has_link=False):
    if (app.status not in amo.WEBAPPS_APPROVED_STATUSES or
        RereviewQueue.objects.filter(addon=app).exists()):
        # If the app isn't public, or has already been reviewed, we don't
        # want to send the mail.
        return

    # FIXME: how to integrate with commbadge?

    for author in app.authors.all():
        context = {
            'error_message': error_message,
            'SITE_URL': settings.SITE_URL,
            'MKT_SUPPORT_EMAIL': settings.MKT_SUPPORT_EMAIL,
            'has_link': has_link
        }
        to = [author.email]
        with author.activate_lang():
            # Re-fetch the app to get translations in the right language.
            context['app'] = Webapp.objects.get(pk=app.pk)

            subject = _(u'Issue with your app "{app}" on the Firefox '
                        u'Marketplace').format(**context)
            send_mail_jinja(subject,
                            'webapps/emails/update_manifest_failure.txt',
                            context, recipient_list=to)


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
        if failed_fetches[id] == 3:
            # This is our 3rd attempt, let's send the developer(s) an email to
            # notify him of the failures.
            notify_developers_of_failure(webapp, u'Validation errors:\n' + msg)
        elif failed_fetches[id] >= 4:
            # This is our 4th attempt, we should already have notified the
            # developer(s). Let's put the app in the re-review queue.
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

    upload = FileUpload.objects.get(pk=upload.pk)
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
                notify_developers_of_failure(webapp, msg, has_link=True)
                RereviewQueue.flag(webapp, amo.LOG.REREVIEW_MANIFEST_CHANGE,
                                   msg)
            return
    else:
        _log(webapp,
             u'Validation for upload UUID %s has no result' % upload.uuid)

    # Get the old manifest before we overwrite it.
    new = json.loads(content)
    old = webapp.get_manifest_json(file_)

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
    # Compare developer_name between old and new version using the property
    # that fallbacks to the author name instead of using the db field directly.
    # This allows us to avoid forcing a re-review on old apps which didn't have
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
    webapp.update_supported_locales(manifest=new)

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
    qs = Webapp.indexing_transformer(Webapp.with_deleted.no_cache().filter(
        id__in=ids))
    for obj in qs:
        doc = WebappIndexer.extract_document(obj.id, obj)
        for idx in indices:
            WebappIndexer.index(doc, id_=obj.id, es=es, index=idx)


@task(acks_late=True)
@write
def unindex_webapps(ids, **kw):
    if not ids:
        return

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
    req.user = AnonymousUser()
    req.REGION = WORLDWIDE

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    task_log.info('Dumping app {0} to {1}'.format(id, target_file))
    res = AppResource().dehydrate_objects([obj], request=req)
    json.dump(res[0], open(target_file, 'w'), cls=JSONEncoder)
    return target_file


@task
def clean_apps(pks, **kw):
    app_dir = os.path.join(settings.DUMPED_APPS_PATH, 'apps')
    if os.path.exists(app_dir):
        shutil.rmtree(app_dir)
    return pks


@task(ignore_result=False)
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


def _fix_missing_icons(id):
    try:
        webapp = Webapp.objects.get(pk=id)
    except Webapp.DoesNotExist:
        _log(id, u'Webapp does not exist')
        return

    # Check for missing icons. If we find one important size missing, call
    # fetch_icon for this app.
    dirname = webapp.get_icon_dir()
    destination = os.path.join(dirname, '%s' % webapp.id)
    for size in (64, 128):
        filename = '%s-%s.png' % (destination, size)
        if not storage.exists(filename):
            _log(id, u'Webapp is missing icon size %d' % (size, ))
            return fetch_icon(webapp)


@task
@write
def fix_missing_icons(ids, **kw):
    for id in ids:
        _fix_missing_icons(id)


@task
@write
def import_manifests(ids, **kw):
    for app in Webapp.objects.filter(id__in=ids):
        for version in app.versions.all():
            try:
                file_ = version.files.latest()
                if file_.status == amo.STATUS_DISABLED:
                    file_path = file_.guarded_file_path
                else:
                    file_path = file_.file_path
                manifest = WebAppParser().get_json_data(file_path)
                m, c = AppManifest.objects.get_or_create(
                    version=version, manifest=json.dumps(manifest))
                if c:
                    task_log.info(
                        '[Webapp:%s] Imported manifest for version %s' % (
                            app.id, version.id))
                else:
                    task_log.info(
                        '[Webapp:%s] App manifest exists for version %s' % (
                            app.id, version.id))
            except Exception as e:
                task_log.info('[Webapp:%s] Error loading manifest for version '
                              '%s: %s' % (app.id, version.id, e))


def _get_trending(app_id, region=None):
    """
    Calculate trending.

    a = installs from 7 days ago to now
    b = installs from 28 days ago to 8 days ago, averaged per week

    trending = (a - b) / b if a > 100 and b > 1 else 0

    """
    client = get_monolith_client()

    kwargs = {'app-id': app_id}
    if region:
        kwargs['region'] = region.slug

    today = datetime.datetime.today()
    days_ago = lambda d: today - datetime.timedelta(days=d)

    # If we query monolith with interval=week and the past 7 days
    # crosses a Monday, Monolith splits the counts into two. We want
    # the sum over the past week so we need to `sum` these.
    try:
        count_1 = sum(
            c['count'] for c in
            client('app_installs', days_ago(7), today, 'week', **kwargs)
            if c.get('count'))
    except ValueError as e:
        task_log.info('Call to ES failed: {0}'.format(e))
        count_1 = 0

    # If count_1 isn't more than 100, stop here to avoid extra Monolith calls.
    if not count_1 > 100:
        return 0.0

    # Get the average installs for the prior 3 weeks. Don't use the `len` of
    # the returned counts because of week boundaries.
    try:
        count_3 = sum(
            c['count'] for c in
            client('app_installs', days_ago(28), days_ago(8), 'week', **kwargs)
            if c.get('count')) / 3
    except ValueError as e:
        task_log.info('Call to ES failed: {0}'.format(e))
        count_3 = 0

    if count_3 > 1:
        return (count_1 - count_3) / count_3
    else:
        return 0.0


@task
@write
def update_trending(ids, **kw):
    count = 0
    times = []

    for app in Webapp.objects.filter(id__in=ids).no_transforms():

        count += 1
        t_start = time.time()

        # Calculate global trending, then per-region trending below.
        value = _get_trending(app.id)
        if value:
            trending, created = app.trending.get_or_create(
                region=0, defaults={'value': value})
            if not created:
                trending.update(value=value)

        for region in mkt.regions.REGIONS_DICT.values():
            value = _get_trending(app.id, region)
            if value:
                trending, created = app.trending.get_or_create(
                    region=region.id, defaults={'value': value})
                if not created:
                    trending.update(value=value)

        times.append(time.time() - t_start)

    task_log.debug('Trending calculated for %s apps. Avg time overall: '
                   '%0.2fs' % (count, sum(times) / count))
