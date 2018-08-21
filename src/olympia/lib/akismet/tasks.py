from olympia.amo.celery import task


@task
def submit_to_akismet(report_ids, submit_spam):
    from .models import AkismetReport  # circular import

    reports = AkismetReport.objects.filter(id__in=report_ids)
    for report in reports:
        report.submit_spam() if submit_spam else report.submit_ham()
