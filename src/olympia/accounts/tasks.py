from datetime import datetime

import olympia.core.logger

from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.accounts')


@task
@use_primary_db
def primary_email_change_event(email, uid, timestamp):
    """Process the primaryEmailChangedEvent."""
    try:
        profile = UserProfile.objects.get(fxa_id=uid)
        changed_date = datetime.fromtimestamp(timestamp)
        if (not profile.email_changed or
                profile.email_changed < changed_date):
            profile.update(email=email, email_changed=changed_date)
            log.info('Account [%s] email [%s] changed from FxA on %s' %
                     (profile.id, email, changed_date))
        else:
            log.warning('Account [%s] email updated ignored, %s > %s' %
                        (profile.id, profile.email_changed, changed_date))
    except ValueError as e:
        log.error(e)
    except UserProfile.MultipleObjectsReturned:
        log.error('Multiple profile matches for FxA id %s' % uid)
    except UserProfile.DoesNotExist:
        log.error('No profile match for FxA id %s' % uid)
