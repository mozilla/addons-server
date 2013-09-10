import waffle

from django.conf import settings


def payments_enabled(request):
    """
    If payments are not limited, anyone can pay.
    If payments are limited, the override-app-payments flag is consulted.
    """
    if not settings.PAYMENT_LIMITED:
        return True

    return waffle.flag_is_active(request, 'override-app-payments')
