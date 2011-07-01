import calendar
import json
import re
import urllib2
from datetime import datetime, timedelta
from subprocess import Popen, PIPE

from django.conf import settings

from celeryutils import task
import cronjobs
import commonware.log
import phpserialize

import amo
from amo.utils import chunked
from addons.models import Addon, AddonCategory
from addons.utils import AdminActivityLogMigrationTracker, MigrationTracker
from applications.models import Application, AppVersion
from bandwagon.models import Collection
from cake.models import Session
from devhub.models import ActivityLog, LegacyAddonLog
from editors.models import EventLog
from files.models import TestResultCache
from reviews.models import Review
from sharing import SERVICES_LIST
from stats.models import AddonShareCount, Contribution
from users.models import UserProfile

log = commonware.log.getLogger('z.cron')


@task
def _trim_categories(results, app_id, **kw):
    """
    `results` is a list of dicts.  E.g.:

    [{'addon_id': 138L, 'num_cats': 4}, ...]
    """
    log.info('[%s@%s] Trimming category-fat add-ons' %
             (len(results), _trim_categories.rate_limit))

    delete_me = []
    pks = [r['addon_id'] for r in results]

    for addon in Addon.objects.filter(pk__in=pks):
        qs = addon.addoncategory_set.filter(category__application=app_id)[2:]
        delete_me.extend(qs.values_list('id', flat=True))

    log.info('Deleting %d add-on categories.' % len(delete_me))
    AddonCategory.objects.filter(pk__in=delete_me).delete()


@cronjobs.register
def gc(test_result=True):
    """Site-wide garbage collections."""

    days_ago = lambda days: datetime.today() - timedelta(days=days)
    one_hour_ago = datetime.today() - timedelta(hours=1)

    log.debug('Collecting data to delete')

    logs = (ActivityLog.objects.filter(created__lt=days_ago(90))
            .exclude(action__in=amo.LOG_KEEP).values_list('id', flat=True))

    # Paypal only keeps retrying to verify transactions for up to 3 days. If we
    # still have an unverified transaction after 6 days, we might as well get
    # rid of it.
    contributions_to_delete = (Contribution.objects
            .filter(transaction_id__isnull=True, created__lt=days_ago(6))
            .values_list('id', flat=True))

    collections_to_delete = (Collection.objects.filter(
            created__lt=days_ago(2), type=amo.COLLECTION_ANONYMOUS)
            .values_list('id', flat=True))

    # Remove Incomplete add-ons older than 4 days.
    addons_to_delete = (Addon.objects.filter(
                        highest_status=amo.STATUS_NULL, status=amo.STATUS_NULL,
                        created__lt=days_ago(4))
                        .values_list('id', flat=True))

    for chunk in chunked(logs, 100):
        _delete_logs.delay(chunk)
    for chunk in chunked(contributions_to_delete, 100):
        _delete_stale_contributions.delay(chunk)
    for chunk in chunked(collections_to_delete, 100):
        _delete_anonymous_collections.delay(chunk)
    for chunk in chunked(addons_to_delete, 100):
        _delete_incomplete_addons.delay(chunk)

    log.debug('Cleaning up sharing services.')
    AddonShareCount.objects.exclude(
            service__in=[s.shortname for s in SERVICES_LIST]).delete()

    log.debug('Cleaning up cake sessions.')
    # cake.Session uses Unix Timestamps
    two_days_ago = calendar.timegm(days_ago(2).utctimetuple())
    Session.objects.filter(expires__lt=two_days_ago).delete()

    log.debug('Cleaning up test results cache.')
    TestResultCache.objects.filter(date__lt=one_hour_ago).delete()

    log.debug('Cleaning up test results extraction cache.')
    if settings.NETAPP_STORAGE and settings.NETAPP_STORAGE != '/':
        cmd = ('find', settings.NETAPP_STORAGE, '-maxdepth', '1', '-name',
               'validate-*', '-mtime', '+7', '-type', 'd',
               '-exec', 'rm', '-rf', "{}", ';')

        output = Popen(cmd, stdout=PIPE).communicate()[0]

        for line in output.split("\n"):
            log.debug(line)

    else:
        log.warning('NETAPP_STORAGE not defined.')

    if settings.COLLECTIONS_ICON_PATH:
        log.debug('Cleaning up uncompressed icons.')

        cmd = ('find', settings.COLLECTIONS_ICON_PATH,
               '-name', '*__unconverted', '-mtime', '+1', '-type', 'f',
               '-exec', 'rm', '{}', ';')
        output = Popen(cmd, stdout=PIPE).communicate()[0]

        for line in output.split("\n"):
            log.debug(line)

    if settings.USERPICS_PATH:
        log.debug('Cleaning up uncompressed userpics.')

        cmd = ('find', settings.USERPICS_PATH,
               '-name', '*__unconverted', '-mtime', '+1', '-type', 'f',
               '-exec', 'rm', '{}', ';')
        output = Popen(cmd, stdout=PIPE).communicate()[0]

        for line in output.split("\n"):
            log.debug(line)


@task
def _delete_logs(items, **kw):
    log.info('[%s@%s] Deleting logs' % (len(items), _delete_logs.rate_limit))
    ActivityLog.objects.filter(pk__in=items).exclude(
            action__in=amo.LOG_KEEP).delete()


@task
def _delete_stale_contributions(items, **kw):
    log.info('[%s@%s] Deleting stale contributions' %
             (len(items), _delete_stale_contributions.rate_limit))
    Contribution.objects.filter(
            transaction_id__isnull=True, pk__in=items).delete()


@task
def _delete_anonymous_collections(items, **kw):
    log.info('[%s@%s] Deleting anonymous collections' %
             (len(items), _delete_anonymous_collections.rate_limit))
    Collection.objects.filter(type=amo.COLLECTION_ANONYMOUS,
                              pk__in=items).delete()


@task
def _delete_incomplete_addons(items, **kw):
    log.info('[%s@%s] Deleting incomplete add-ons' %
             (len(items), _delete_incomplete_addons.rate_limit))
    for addon in Addon.objects.filter(
            highest_status=0, status=0, pk__in=items):
        try:
            addon.delete('Deleted for incompleteness')
        except Exception as e:
            log.error("Couldn't delete add-on %s: %s" % (addon.id, e))


@cronjobs.register
def migrate_admin_logs():
    # Get the highest id we've looked at.
    a = AdminActivityLogMigrationTracker()
    id = a.get() or 0

    # filter here for addappversion
    items = LegacyAddonLog.objects.filter(
            type=amo.LOG.ADD_APPVERSION.id, pk__gt=id).values_list(
            'id', flat=True)
    for chunk in chunked(items, 100):
        _migrate_admin_logs.delay(chunk)
        a.set(chunk[-1])


@task
def _migrate_admin_logs(items, **kw):
    print 'Processing: %d..%d' % (items[0], items[-1])
    for item in LegacyAddonLog.objects.filter(pk__in=items):
        kw = dict(user=item.user, created=item.created)
        amo.log(amo.LOG.ADD_APPVERSION, (Application, item.object1_id),
                (AppVersion, item.object2_id), **kw)


# TODO(davedash): remove after /editors is on zamboni
@cronjobs.register
def migrate_editor_eventlog():
    a = MigrationTracker('eventlog')
    id = a.get() or 0

    items = EventLog.objects.filter(type='editor', pk__gt=id).values_list(
            'id', flat=True)

    for chunk in chunked(items, 100):
        _migrate_editor_eventlog(chunk)
        a.set(chunk[-1])


@task
def _migrate_editor_eventlog(items, **kw):
    log.info('[%s@%s] Migrating eventlog items' %
             (len(items), _migrate_editor_eventlog.rate_limit))
    for item in EventLog.objects.filter(pk__in=items):
        kw = dict(user=item.user, created=item.created)
        if item.action == 'review_delete':
            details = None
            try:
                details = phpserialize.loads(item.notes)
            except ValueError:
                pass
            amo.log(amo.LOG.DELETE_REVIEW, item.changed_id, details=details,
                    **kw)
        elif item.action == 'review_approve':
            try:
                r = Review.objects.get(pk=item.changed_id)
                amo.log(amo.LOG.ADD_REVIEW, r, r.addon, **kw)
            except Review.DoesNotExist:
                log.warning("Couldn't find review for %d" % item.changed_id)


@cronjobs.register
def dissolve_outgoing_urls():
    """Over time, some outgoing.m.o URLs have been encoded several times in the
    db.  This removes the layers of encoding and sets URLs to their real value.
    The app will take care of sending things through outgoing.m.o.  See bug
    608117."""

    needle = 'outgoing.mozilla.org'

    users = (UserProfile.objects.filter(homepage__contains=needle)
             .values_list('id', 'homepage'))

    if not users:
        print "Didn't find any add-ons with messed up homepages."
        return

    print 'Found %s users to fix.  Sending them to celeryd.' % len(users)

    for chunk in chunked(users, 100):
        _dissolve_outgoing_urls.delay(chunk)


@task(rate_limit='60/h')
def _dissolve_outgoing_urls(items, **kw):
    log.info('[%s@%s] Dissolving outgoing urls' %
             (len(items), _dissolve_outgoing_urls.rate_limit))

    regex = re.compile('^http://outgoing.mozilla.org/v1/[0-9a-f]+/(.*?)$')

    def peel_the_onion(url):
        match = regex.match(url)

        if not match:
            return None

        new = urllib2.unquote(match.group(1))
        are_we_there_yet = peel_the_onion(new)  # That's right. You love it.

        if not are_we_there_yet:
            return new
        else:
            return are_we_there_yet

    for user in items:
        url = peel_the_onion(user[1])

        # 20 or so of these are just to outgoing.m.o, so just whack them
        if url == 'http://outgoing.mozilla.org':
            url = None

        UserProfile.objects.filter(pk=user[0]).update(homepage=url)


# TODO(davedash): Remove after 5.12.7 is pushed.
@cronjobs.register
def activity_log_scrubber():
    """
    Scans activity log for REMOVE_FROM_COLLECTION and ADD_TO_COLLECTION, looks
    for collections in arguments and checks whether collection is listed.
    """

    items = (ActivityLog.objects.filter(
             action__in=[amo.LOG.ADD_TO_COLLECTION.id,
                         amo.LOG.REMOVE_FROM_COLLECTION.id])
             .values('id', '_arguments'))
    ids = []
    count = 0
    # ~127K
    for item in items:
        count += 1
        for k in json.loads(item['_arguments']):
            if 'bandwagon.collection' not in k:
                continue
            if not all(Collection.objects.filter(pk=k.values()[0])
                       .values_list('listed', flat=True)):
                log.debug('%d items seen.' % count)
                ids.append(item['id'])
        if len(ids) > 100:
            _activity_log_scrubber.delay(ids)
            ids = []

    # get everyone else
    _activity_log_scrubber.delay(ids)


@task(rate_limit='60/h')
def _activity_log_scrubber(items, **kw):
    log.info('[%s@%s] Deleting activity log items' %
             (len(items), _activity_log_scrubber.rate_limit))

    ActivityLog.objects.filter(id__in=items).delete()
