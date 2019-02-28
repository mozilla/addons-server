from django.views.decorators.cache import never_cache

from olympia.amo.utils import render

from olympia.users import notifications as notifications
from olympia.users.models import UserNotification

from .models import UserProfile
from .utils import UnsubscribeCode


@never_cache
def unsubscribe(request, hash=None, token=None, perm_setting=None):
    """
    Pulled from django contrib so that we can add user into the form
    so then we can show relevant messages about the user.
    """
    assert hash is not None and token is not None
    user = None

    try:
        email = UnsubscribeCode.parse(token, hash)
        user = UserProfile.objects.get(email=email)
    except (ValueError, UserProfile.DoesNotExist):
        pass

    perm_settings = []
    if user is not None and perm_setting is not None:
        unsubscribed = True
        perm_setting = notifications.NOTIFICATIONS_BY_SHORT[perm_setting]
        UserNotification.objects.update_or_create(
            user=user, notification_id=perm_setting.id,
            defaults={'enabled': False})
        perm_settings = [perm_setting]
    else:
        unsubscribed = False
        email = ''

    return render(request, 'users/unsubscribe.html',
                  {'unsubscribed': unsubscribed, 'email': email,
                   'perm_settings': perm_settings})
