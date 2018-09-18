from django.utils.encoding import smart_str
from django.core.serializers import deserialize as object_deserialize

from olympia.amo.celery import task

from .models import AkismetReport


@task
def submit_to_akismet(report_ids, submit_spam):
    reports = AkismetReport.objects.filter(id__in=report_ids)
    for report in reports:
        report.submit_spam() if submit_spam else report.submit_ham()


@task
def comment_check(report_ids):
    reports = AkismetReport.objects.filter(id__in=report_ids)
    return [report.comment_check() for report in reports]


@task
def save_akismet_report(xml):
    reports = object_deserialize("xml", smart_str(xml))
    for report in reports:
        report.save()
