import functools
from datetime import datetime

import olympia.core.logger

from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.accounts')


def user_profile_from_uid(f):
    @functools.wraps(f)
    def wrapper(uid, timestamp, *args, **kw):
        try:
            timestamp = datetime.fromtimestamp(timestamp)
            profile = UserProfile.objects.get(fxa_id=uid)
            return f(profile, timestamp, *args, **kw)
        except ValueError as e:
            log.warning(e)
        except UserProfile.MultipleObjectsReturned:
            log.warning('Multiple profile matches for FxA id %s' % uid)
        except UserProfile.DoesNotExist:
            log.info('No profile match for FxA id %s' % uid)
    return wrapper


@task
@use_primary_db
@user_profile_from_uid
def primary_email_change_event(profile, changed_date, email):
    """Process the primaryEmailChangedEvent."""
    if (not profile.email_changed or
            profile.email_changed < changed_date):
        profile.update(email=email, email_changed=changed_date)
        log.info(
            'Account pk [%s] email [%s] changed from FxA on %s' % (
                profile.id, email, changed_date))
    else:
        log.warning('Account pk [%s] email updated ignored, %s > %s' %
                    (profile.id, profile.email_changed, changed_date))


@task
@use_primary_db
@user_profile_from_uid
def delete_user_event(user, deleted_date):
    """Process the delete user event."""
    user.delete(
        related_content=True,
        addon_msg='Deleted via FxA account deletion')
    log.info(
        'Account pk [%s] deleted from FxA on %s' % (user.id, deleted_date))
