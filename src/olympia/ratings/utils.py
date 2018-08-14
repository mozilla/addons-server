import waffle

from .tasks import check_with_akismet


def maybe_check_with_akismet(request, instance, pre_save_body):
    should_check = (
        instance.body and instance.body != pre_save_body and
        getattr(instance, 'user_responsible', None) == instance.user and
        waffle.switch_is_active('akismet-spam-check'))
    if should_check:
        check_with_akismet.delay(
            instance.id,
            request.META.get('HTTP_USER_AGENT'),
            request.META.get('HTTP_REFERER'))
        return True
    return False
