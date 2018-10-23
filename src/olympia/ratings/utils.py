import waffle

from olympia.lib.akismet.models import AkismetReport

from .tasks import check_akismet_reports


def maybe_check_with_akismet(request, instance, pre_save_body):
    akismet_reports = get_rating_akismet_reports(
        request, instance, pre_save_body)
    if akismet_reports:
        check_akismet_reports.delay([rep.id for rep in akismet_reports])
    return akismet_reports != []


def get_rating_akismet_reports(request, instance, pre_save_body):
    should_check = (
        instance.body and instance.body != pre_save_body and
        getattr(instance, 'user_responsible', None) == instance.user and
        waffle.switch_is_active('akismet-spam-check'))
    if should_check:
        return [AkismetReport.create_for_rating(
            instance,
            request.META.get('HTTP_USER_AGENT'),
            request.META.get('HTTP_REFERER'))]
    return []
