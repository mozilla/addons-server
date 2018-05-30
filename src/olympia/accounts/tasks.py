from dateutil.parser import parse as dateutil_parser

import olympia.core.logger

from olympia.amo.celery import task
from olympia.amo.decorators import write
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.accounts')


@task
@write
def primary_email_change_event(email, uid, timestamp):
    """Process the primaryEmailChangedEvent."""
    try:
        profile = UserProfile.objects.get(fxa_id=uid)
        timestamp = dateutil_parser(timestamp)
        if (not profile.email_changed or
                profile.email_changed < timestamp):
            profile.update(email=email, email_changed=timestamp)
            log.info('Account [%s] email [%s] changed from FxA on %s' %
                     (profile.id, email, timestamp))
        else:
            log.warning('Account [%s] email updated ignored, %s > %s' %
                        (profile.id, profile.email_changed, timestamp))
    except ValueError as e:
        log.error(e)
    except UserProfile.MultipleObjectsReturned:
        log.error('Multiple profile matches for FxA id %s' % uid)
    except UserProfile.DoesNotExist:
        log.error('No profile match for FxA id %s' % uid)
