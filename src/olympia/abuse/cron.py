from datetime import datetime, timedelta

from django.template import loader

from olympia.amo.utils import send_mail

from .models import AbuseReport, CinderJob


def reports_without_cinder_id_qs():
    """check for any abuse reports that have been created more than an hour ago and
    don’t have a cinder job yet"""
    one_hour_ago = datetime.now() - timedelta(hours=1)
    return AbuseReport.objects.filter(
        reason__in=tuple(AbuseReport.REASONS.REPORTABLE_REASONS.values),
        cinder_job_id__isnull=True,
        created__lt=one_hour_ago,
    )


def unresolved_cinder_handled_jobs_qs():
    """check for any abuse reports created more than Y business days ago that have a
    cinder job ID but don’t have a cinder decision."""
    sla_date = datetime.now() - timedelta(days=3)
    return (
        CinderJob.objects.unresolved()
        .exclude(
            id__in=CinderJob.objects.resolvable_in_reviewer_tools().values_list(
                'id', flat=True
            )
        )
        .filter(created__lt=sla_date)
    )


def unresolved_reviewers_handled_jobs_qs():
    """check for any abuse reports created more than X business days ago that have a
    cinder job ID but doesn’t have an AMO decision."""
    sla_date = datetime.now() - timedelta(days=3)
    return (
        CinderJob.objects.unresolved()
        .resolvable_in_reviewer_tools()
        .filter(created__lt=sla_date)
    )


def abuse_report_health_checks():
    for subject, to, template_file, qs in (
        (
            '%s abuse reports without a cinder_job',
            ['andreas@'],
            'no_cinder_id.txt',
            reports_without_cinder_id_qs,
        ),
        (
            '%s unresolved AMO reviewer tools handled jobs beyond SLA',
            ['andreas@'],
            'unresolved_jobs.txt',
            unresolved_cinder_handled_jobs_qs,
        ),
        (
            '%s unresolved Cinder moderator handled jobs beyond SLA',
            ['andreas@'],
            'unresolved_jobs.txt',
            unresolved_reviewers_handled_jobs_qs,
        ),
    ):
        if results := list(qs):
            template = loader.get_template(f'abuse/emails/cron/{template_file}')
            send_mail(
                subject.format(len(results)),
                template.render({'results': results}),
                recipient_list=tuple(to),
            )
