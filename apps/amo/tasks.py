import datetime

from django.conf import settings

import commonware.log
import phpserialize
from celeryutils import task
from hera.contrib.django_utils import flush_urls

import amo
from abuse.models import AbuseReport
from addons.models import Addon
from applications.models import Application, AppVersion
from bandwagon.models import Collection
from devhub.models import ActivityLog, AppLog, LegacyAddonLog
from editors.models import EscalationQueue, EventLog
from market.models import Refund
from reviews.models import Review
from stats.models import Contribution
from users.utils import get_task_user


log = commonware.log.getLogger('z.task')


@task
def flush_front_end_cache_urls(urls, **kw):
    """Accepts a list of urls which will be sent through Hera to the front end
    cache.  This does no checking for success or failure or whether the URLs
    were in the cache to begin with."""

    if not urls:
        return

    log.info(u"Flushing %d URLs from front end cache: (%s)" % (len(urls),
                                                               urls))

    # Zeus is only interested in complete URLs.  We can't just pass a
    # prefix to Hera because some URLs will be on SAMO.
    for index, url in enumerate(urls):
        if not url.startswith('http'):
            if '/api/' in url:
                urls[index] = u"%s%s" % (settings.SERVICES_URL, url)
            else:
                urls[index] = u"%s%s" % (settings.SITE_URL, url)

    flush_urls(urls)


@task
def set_modified_on_object(obj, **kw):
    """Sets modified on one object at a time."""
    try:
        log.info('Setting modified on object: %s, %s' %
                 (obj.__class__.__name__, obj.pk))
        obj.update(modified=datetime.datetime.now())
    except Exception, e:
        log.error('Failed to set modified on: %s, %s - %s' %
                  (obj.__class__.__name__, obj.pk, e))


@task
def delete_logs(items, **kw):
    log.info('[%s@%s] Deleting logs' % (len(items), delete_logs.rate_limit))
    ActivityLog.objects.filter(pk__in=items).exclude(
            action__in=amo.LOG_KEEP).delete()


@task
def delete_stale_contributions(items, **kw):
    log.info('[%s@%s] Deleting stale contributions' %
             (len(items), delete_stale_contributions.rate_limit))
    Contribution.objects.filter(
            transaction_id__isnull=True, pk__in=items).delete()


@task
def delete_anonymous_collections(items, **kw):
    log.info('[%s@%s] Deleting anonymous collections' %
             (len(items), delete_anonymous_collections.rate_limit))
    Collection.objects.filter(type=amo.COLLECTION_ANONYMOUS,
                              pk__in=items).delete()


@task
def delete_incomplete_addons(items, **kw):
    log.info('[%s@%s] Deleting incomplete add-ons' %
             (len(items), delete_incomplete_addons.rate_limit))
    for addon in Addon.objects.filter(
            highest_status=0, status=0, pk__in=items):
        try:
            addon.delete('Deleted for incompleteness')
        except Exception as e:
            log.error("Couldn't delete add-on %s: %s" % (addon.id, e))


@task
def migrate_admin_logs(items, **kw):
    print 'Processing: %d..%d' % (items[0], items[-1])
    for item in LegacyAddonLog.objects.filter(pk__in=items):
        kw = dict(user=item.user, created=item.created)
        amo.log(amo.LOG.ADD_APPVERSION, (Application, item.object1_id),
                (AppVersion, item.object2_id), **kw)


@task
def migrate_editor_eventlog(items, **kw):
    log.info('[%s@%s] Migrating eventlog items' %
             (len(items), migrate_editor_eventlog.rate_limit))
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


@task
def find_abuse_escalations(addon_id, **kw):
    amo.set_user(get_task_user())
    weekago = datetime.date.today() - datetime.timedelta(days=7)

    for abuse in AbuseReport.recent_high_abuse_reports(1, weekago, addon_id):
        if EscalationQueue.objects.filter(addon=abuse.addon).exists():
            # App is already in the queue, no need to re-add it.
            # TODO: If not in queue b/c of abuse reports, add an
            #       amo.LOG.ESCALATED_HIGH_ABUSE for reviewers.
            log.info(u'[addon:%s] High abuse reports, but already escalated' %
                     (abuse.addon,))
            continue

        # We have an abuse report and this add-on isn't currently in the
        # escalated queue... let's see if it has been detected and dealt with
        # already.
        logs = (AppLog.objects.filter(
            activity_log__action=amo.LOG.ESCALATED_HIGH_ABUSE.id,
            addon=abuse.addon).order_by('-created'))
        if logs:
            abuse_since_log = AbuseReport.recent_high_abuse_reports(
                1, logs[0].created, addon_id)
            # If no abuse reports have happened since the last logged abuse
            # report, do not add to queue.
            if not abuse_since_log:
                log.info(u'[addon:%s] High abuse reports, but none since last '
                          'escalation' % abuse.addon)
                continue

        # If we haven't bailed out yet, escalate this app.
        msg = u'High number of abuse reports detected'
        EscalationQueue.objects.create(addon=abuse.addon)
        amo.log(amo.LOG.ESCALATED_HIGH_ABUSE, abuse.addon,
                abuse.addon.current_version, details={'comments': msg})
        log.info(u'[addon:%s] %s' % (abuse.addon, msg))


@task
def find_refund_escalations(addon_id, **kw):
    try:
        addon = Addon.objects.get(pk=addon_id)
    except Addon.DoesNotExist:
        log.info(u'[addon:%s] Task called but no addon found.' % addon_id)
        return

    refund_threshold = 0.05
    amo.set_user(get_task_user())
    weekago = datetime.date.today() - datetime.timedelta(days=7)

    ratio = Refund.recent_refund_ratio(addon.id, weekago)
    if ratio > refund_threshold:
        if EscalationQueue.objects.filter(addon=addon).exists():
            # App is already in the queue, no need to re-add it.
            # TODO: If not in queue b/c of refunds, add an
            #       amo.LOG.ESCALATED_HIGH_REFUNDS for reviewers.
            log.info(u'[addon:%s] High refunds, but already escalated' % addon)
            return

        # High refunds and app isn't in the escalation queue...  let's see if
        # it has been detected and dealt with already.
        logs = (AppLog.objects.filter(
            activity_log__action=amo.LOG.ESCALATED_HIGH_REFUNDS.id,
            addon=addon).order_by('-created'))
        if logs:
            since_ratio = Refund.recent_refund_ratio(addon.id, logs[0].created)
            # If not high enough ratio since the last logged, do not add to
            # the queue.
            if not since_ratio > refund_threshold:
                log.info(u'[addon:%s] High refunds, but not enough since last '
                          'escalation. Ratio: %.0f%%' % (addon,
                                                         since_ratio * 100))
                return

        # If we haven't bailed out yet, escalate this app.
        msg = u'High number of refund requests (%.0f%%) detected.' % (
            (ratio * 100),)
        EscalationQueue.objects.create(addon=addon)
        amo.log(amo.LOG.ESCALATED_HIGH_REFUNDS, addon,
                addon.current_version, details={'comments': msg})
        log.info(u'[addon:%s] %s' % (addon, msg))
