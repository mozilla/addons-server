import functools
from datetime import datetime

from waffle import switch_is_active

import olympia.core.logger
from olympia import amo
from olympia.activity.models import ActivityLog
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
def primary_email_change_event(user, event_date, email):
    """Process the primaryEmailChangedEvent."""
    if not user.email_changed or user.email_changed < event_date:
        user.update(email=email, email_changed=event_date)
        log.info(
            'Account pk [%s] email [%s] changed from FxA on %s'
            % (user.id, email, event_date)
        )
    else:
        log.warning(
            'Account pk [%s] email updated ignored, %s >= %s'
            % (user.id, user.email_changed, event_date)
        )


@task
@use_primary_db
@user_profile_from_uid
def delete_user_event(user, event_date):
    """Process the delete user event."""
    if switch_is_active('fxa-account-delete'):
        ActivityLog.create(amo.LOG.USER_AUTO_DELETED, user, user=user)
        user.delete(addon_msg='Deleted via FxA account deletion')
        log.info(f'Account pk [{user.id}] deleted from FxA on {event_date}')
    else:
        log.info(
            f'Skipping deletion from FxA for account [{user.id}] because '
            'waffle inactive'
        )


@task
@use_primary_db
@user_profile_from_uid
def clear_sessions_event(user, event_date, event_type):
    """Process the passwordChange or reset events - both just clear sessions."""
    if not user.last_login or user.last_login < event_date:
        # Logging out invalidates *all* user sessions. A new auth_id will be
        # generated during the next login.
        user.update(auth_id=None)
        log.info(
            'Account pk [%s] sessions reset after a %s event from FxA on %s'
            % (user.id, event_type, event_date)
        )
    else:
        log.warning(
            'Account pk [%s] sessions not reset.  %s event ignored, %s >= %s'
            % (user.id, event_type, user.last_login, event_date)
        )
