import calendar
import json
import re
import time
import urllib2
from datetime import datetime, timedelta
from subprocess import Popen, PIPE

from django.conf import settings
from django.db.models import Count

from celery.messaging import establish_connection
from celeryutils import task
import cronjobs
import commonware.log
import phpserialize
import redisutils

import amo
from amo.utils import chunked
from addons.models import Addon, AddonCategory, Category
from addons.utils import AdminActivityLogMigrationTracker, MigrationTracker
from applications.models import Application, AppVersion
from bandwagon.models import Collection
from cake.models import Session
from devhub.models import ActivityLog, LegacyAddonLog
from editors.models import EventLog
from files.models import Approval, TestResultCache
from reviews.models import Review
from sharing import SERVICES_LIST
from stats.models import AddonShareCount, Contribution
from users.models import UserProfile

log = commonware.log.getLogger('z.cron')


# TODO(davedash): Delete me after this has been run.
@cronjobs.register
def remove_extra_cats():
    """
    Remove 'misc' category if other categories are present.
    Remove categories in excess of two categories.
    """
    # Remove misc categories from addons if they are also in other categories
    # for that app.
    for cat in Category.objects.filter(misc=True):
        # Find all the add-ons in this category.
        addons_in_misc = cat.addon_set.values_list('id', flat=True)
        delete_me = []

        # Count the categories they have per app.
        cat_count = (AddonCategory.objects.values('addon')
                     .annotate(num_cats=Count('category'))
                     .filter(num_cats__gt=1, addon__in=addons_in_misc,
                             category__application=cat.application_id))

        delete_me = [item['addon'] for item in cat_count]
        log.info('Removing %s from %d add-ons' % (cat, len(delete_me)))
        (AddonCategory.objects.filter(category=cat, addon__in=delete_me)
         .delete())

    with establish_connection() as conn:
        # Remove all but 2 categories from everything else, per app
        for app in amo.APP_USAGE:
            # SELECT
            #   `addons_categories`.`addon_id`,
            #   COUNT(`addons_categories`.`category_id`) AS `num_cats`
            # FROM
            #   `addons_categories` INNER JOIN `categories` ON
            #   (`addons_categories`.`category_id` = `categories`.`id`)
            # WHERE
            #   (`categories`.`application_id` = 1 )
            # GROUP BY
            #   `addons_categories`.`addon_id`
            # HAVING COUNT(`addons_categories`.`category_id`) > 2
            log.info('Examining %s add-ons' % unicode(app.pretty))
            results = (AddonCategory.objects
                       .filter(category__application=app.id)
                       .values('addon_id').annotate(num_cats=Count('category'))
                       .filter(num_cats__gt=2))
            for chunk in chunked(results, 100):
                _trim_categories.apply_async(args=[chunk, app.id],
                                             connection=conn)


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

    with establish_connection() as conn:
        for chunk in chunked(logs, 100):
            _delete_logs.apply_async(args=[chunk], connection=conn)
        for chunk in chunked(contributions_to_delete, 100):
            _delete_stale_contributions.apply_async(
                    args=[chunk], connection=conn)
        for chunk in chunked(collections_to_delete, 100):
            _delete_anonymous_collections.apply_async(
                    args=[chunk], connection=conn)
        for chunk in chunked(addons_to_delete, 100):
            _delete_incomplete_addons.apply_async(
                    args=[chunk], connection=conn)

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
    log.info('[%s@%s] Deleting stale collections' %
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


# TODO(andym): Remove after editors/performace is on zamboni
@cronjobs.register
def migrate_activity_log():
    a = MigrationTracker('activity_log')
    id = a.get()
    # Magic date, when 6.0.3 went out, plus a few hours. Because there were
    # items migrated from Approvals over to the ActivityLog, the id cannot
    # be relied upon, so make sure to keeping filtering by the date.
    date = datetime(2011, 4, 1, 0, 0, 0)
    if not id:
        log.info('Migrate activity log seed not found.')
        logs = ActivityLog.objects.filter(created__gte=date).order_by('id')
        if not logs:
            log.info('No activity logs to migrate.')
            return
        id = logs[0].pk - 1  # -1 because we are doing a pk__gt lookup
        log.info('Staring migration at: %s' % id)

    items = list(ActivityLog.objects.filter(pk__gt=id)
                                    .filter(created__gte=date)
                                    .filter(action__in=amo.LOG_REVIEW_QUEUE)
                                    .values_list('id', flat=True)
                                    .order_by('id'))[:100]

    log.info('Found: %d items to migrate' % len(items))
    if items:
        _migrate_activity_log(items)
        a.set(id)


@task
def _migrate_activity_log(items, **kw):
    log.info('[%s@%s] Migrating back activity_log items starting with id: %s' %
             (len(items), _migrate_activity_log.rate_limit, items[0]))

    for item in ActivityLog.objects.filter(pk__in=items):
        kw = dict(user=item.user,
                  created=item.created,
                  action=item.action,
                  comments=str(item),
                  addon=item.arguments[0],
                  reviewtype=item.details['reviewtype'])

        if item.action == amo.LOG.APPROVE_VERSION.id:
            kw['action'] = amo.STATUS_PUBLIC
        elif item.action == amo.LOG.PRELIMINARY_VERSION.id:
            kw['action'] = amo.STATUS_LITE
        elif item.action == amo.LOG.REJECT_VERSION.id:
            kw['action'] = amo.STATUS_NULL
        elif item.action == amo.LOG.ESCALATE_VERSION.id:
            kw['action'] = amo.STATUS_NOMINATED
        elif item.action == amo.LOG.RETAIN_VERSION.id:
            kw['action'] = amo.STATUS_UNREVIEWED
        else:
            log.info('Unknown action %d for %d' % (item.action, item.pk))
            continue

        approval = Approval.objects.create(**kw)
        log.info('Migrated activity log %d over to approval %d' %
                 (item.pk, approval.pk))


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


class QueueCheck(object):
    key = 'cron:queuecheck:%s:%s'

    def __init__(self):
        self.redis = redisutils.connections['master']

    def queues(self):
        # Figure out all the queues we're using. celery is the default, with a
        # warning threshold of 10 minutes.
        queues = {'celery': 60 * 60}
        others = set(r['queue'] for r in settings.CELERY_ROUTES.values())
        # 30 second threshold for the fast queues.
        queues.update((q, 30) for q in others)
        return queues

    def set(self, action, queue):
        self.redis.set(self.key % (action, queue), time.time())

    def get(self, action, queue):
        return self.redis.get(self.key % (action, queue))


@cronjobs.register
def check_queues():
    checker = QueueCheck()
    for queue in checker.queues():
        checker.set('ping', queue)
        ping.apply_async(queue=queue, routing_key=queue, exchange=queue)


@task
def ping(**kw):
    queue = kw['delivery_info']['routing_key']
    log.info('[1@None] Checking the %s queue' % queue)
    QueueCheck().set('pong', queue)


# TODO(davedash): run once
@cronjobs.register
def delete_brand_thunder_addons():
    ids = (102188, 102877, 103381, 103382, 103388, 107864, 109233, 109242,
           111144, 111145, 115970, 150367, 146373, 143547, 142886, 140931,
           113511, 100304, 130876, 126516, 124495, 123900, 120683, 159626,
           159625, 157780, 157776, 155494, 155489, 155488, 152740, 152739,
           151187, 193275, 184048, 182866, 179429, 179426, 161783, 161781,
           161727, 160426, 160425, 220155, 219726, 219724, 219723, 219722,
           218413, 200756, 200755, 199904, 221522, 221521, 221520, 221513,
           221509, 221508, 221505, 220882, 220880, 220879, 223384, 223383,
           223382, 223381, 223380, 223379, 223378, 223376, 222194, 221524,
           223403, 223402, 223400, 223399, 223398, 223388, 223387, 223386,
           223385, 232687, 232681, 228394, 228393, 228392, 228391, 228390,
           226428, 226427, 226388, 235892, 235836, 235277, 235276, 235274,
           232709, 232708, 232707, 232694, 232688, 94461, 94452, 54288, 50418,
           49362, 49177, 239113, 102186, 102185, 101166, 101165, 101164,
           99010, 99007, 99006, 98429, 98428, 45834, 179542, 103383)

    for addon in (UserProfile.objects.get(email='patrick@brandthunder.com')
                  .addons.filter(pk__in=ids)):
        try:
            addon.delete('Deleting per Brand Thunder request (bug 636834).')
        except:
            log.error('Could not delete add-on %d' % addon.id)
