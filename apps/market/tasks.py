import json
import logging
import time

from django.conf import settings

from addons.models import Addon
import amo
from amo.decorators import redis
from amo.helpers import absolutify, loc
from amo.utils import send_mail
from paypal.check import Check
from users.utils import get_task_user

from celeryutils import task
from jingo import env
from waffle import Sample, switch_is_active

log = logging.getLogger('z.market.task')
key = 'amo:market:check_paypal'
failures = '%s:failure' % key
passes = '%s:passes' % key


@redis
def check_paypal_multiple(redis, ids, limit=None):
    """
    Setup redis so that we can store the count of addons tested and failed
    and spot when the test is completed.

    ids: Is the add-on ids we'll be checking.
    limit: The percentage of add-ons to change before we assume something
           has gone wrong. Setting this to zero (not recommended) disables it.
           If not set, we'll use the paypal-disabled-limit waffle sample
           value.
    """
    if limit is None:
        limit = Sample.objects.get(name='paypal-disabled-limit').percent

    log.info('Starting run of paypal addon checks: %s' % len(ids))
    redis.hmset(key, {'started': time.time(), 'count': len(ids),
                      'limit': float(limit)})
    for k in [failures, passes]:
        redis.delete(k)

    return ids


@redis
def _check_paypal_completed(redis):
    started, count, limit = redis.hmget(key, ['started', 'count', 'limit'])
    limit, count = float(limit), int(count)
    failed, passed = redis.llen(failures), redis.llen(passes)
    if (failed + passed) < count:
        return False

    context = {'checked': count, 'failed': failed, 'passed': passed,
               'limit': limit, 'rate': (failed / float(count)) * 100,
               'do_disable': switch_is_active('paypal-disable')}
    _notify(context)
    return True


@redis
def _notify(redis, context):
    """
    Notify the admins or the developers what happened. Performing a sanity
    check in case something went wrong.
    """
    log.info('Completed run of paypal addon checks: %s' % context['checked'])
    failure_list = []

    if context['limit'] and context['rate'] > context['limit']:
        # This is too cope with something horrible going wrong like, paypal
        # goes into maintenance mode, or netops changes something and all of
        # a sudden all the apps start failing their paypal checks.
        #
        # It would really suck if one errant current job disabled every app
        # on the marketplace. So this is an attempt to sanity check this.
        for k in xrange(context['failed']):
            data = json.loads(redis.lindex(failures, k))
            addon = Addon.objects.get(pk=data[0])
            failure_list.append(absolutify(addon.get_url_path()))

        context['failure_list'] = failure_list
        log.info('Too many failed: %s%%, aborting.' % context['limit'])
        template = 'market/emails/check_error.txt'
        send_mail('Cron job error on checking addons',
                  env.get_template(template).render(context),
                  recipient_list=[settings.FLIGTAR],
                  from_email=settings.NOBODY_EMAIL)

    else:
        if not context['failed']:
            return

        for k in xrange(context['failed']):
            data = json.loads(redis.lindex(failures, k))
            addon = Addon.objects.get(pk=data[0])
            url = absolutify(addon.get_url_path())
            # Add this to a list so we can tell the admins who got disabled.
            failure_list.append(url)
            if not context['do_disable']:
                continue

            # Write to the developers log that it failed to pass and update
            # the status of the addon.
            amo.log(amo.LOG.PAYPAL_FAILED, addon, user=get_task_user())
            addon.update(status=amo.STATUS_DISABLED)

            authors = [u.email for u in addon.authors.all()]
            if addon.is_webapp():
                template = 'market/emails/check_developer_app.txt'
                subject = loc('App disabled on the Mozilla Market.')
            else:
                template = 'market/emails/check_developer_addon.txt'
                subject = loc('Add-on disabled on the Mozilla Market.')

            # Now email the developer and tell them the bad news.
            send_mail(subject,
                      env.get_template(template).render({
                          'addon': addon,
                          'errors': data[1:]
                      }),
                      recipient_list=authors,
                      from_email=settings.NOBODY_EMAIL)

        context['failure_list'] = failure_list
        # Now email the admins and tell them what happened.
        template = 'market/emails/check_summary.txt'
        send_mail('Cron job disabled %s add-ons' % context['failed'],
                  env.get_template(template).render(context),
                  recipient_list=[settings.FLIGTAR],
                  from_email=settings.NOBODY_EMAIL)


@task(rate_limit='4/m')
@redis
def check_paypal(redis, ids, check=None, **kw):
    """
    Checks an addon against PayPal for the following things:
    - that the refund token is still there
    - that they have enough currency
    If the addon fails any of these tests then we'll log, email the developer
    and alter the apps status so that it can't be bought.
    This will be doing lots of pings to PayPal so I expect it to be pretty
    slow.
    """
    log.info('[%s@%s] checking paypal for addons starting with: %s'
             % (len(ids), check_paypal.rate_limit, ids[0]))

    if check is None:
        check = Check

    for id in ids:
        try:
            addon = Addon.objects.get(pk=id)
            log.info('Checking paypal for: %s' % addon.id)
            result = check(addon=addon)
            result.all()
            if result.passed:
                redis.rpush(passes, id)
                log.info('Paypal checks all passed for: %s' % id)
            else:
                redis.rpush(failures, json.dumps([id, ] + result.errors))
                log.info('Paypal checks failed for: %s' % id)

        except:
            # Note I'm marking this as a pass, because marking it as a failure
            # would cause the app to be marked as disabled and I think that's
            # the wrong thing to do.
            log.error('Paypal check failed: %s' % id, exc_info=True)
            redis.rpush(passes, id)

        # Finally call to see if we've finished.
        _check_paypal_completed()
