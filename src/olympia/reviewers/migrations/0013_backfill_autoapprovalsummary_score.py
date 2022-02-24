# Generated by Django 2.2.17 on 2021-01-15 12:07

from django.db import migrations
from django.db.models import F, IntegerField, OuterRef, Subquery
from django.db.models.functions import Cast

from olympia.constants.base import STATUS_APPROVED
from olympia.constants.scanners import MAD


def forwards_func(apps, schema_editor):
    AutoApprovalSummary = apps.get_model('reviewers', 'AutoApprovalSummary')
    ScannerResult = apps.get_model('scanners', 'ScannerResult')

    AutoApprovalSummary.objects.filter(
        confirmed=None,
        version__deleted=False,
        version__addon__status=STATUS_APPROVED,
        version__addon___current_version=F('version'),
        version__scannerresults__score__gt=0,
        version__scannerresults__scanner=MAD,
    ).update(
        # Django doesn't let us simply do F('version__scannerresults__score'),
        # So we recompute that from a subquery. Note that we have to re-apply
        # the filtering to make sure we get the right ScannerResult, and that
        # we have to cast and multiply by 100 to match the way we store scores
        # in AutoApprovalSummary.
        score=Cast(
            Subquery(
                ScannerResult.objects.filter(
                    version=OuterRef('version'),
                    scanner=MAD,
                ).values('score')[:1]
            )
            * 100,
            IntegerField(),
        )
    )


def reverse_func(apps, schema_editor):
    AutoApprovalSummary = apps.get_model('reviewers', 'AutoApprovalSummary')
    AutoApprovalSummary.objects.filter(score__isnull=False).update(score=None)


class Migration(migrations.Migration):

    dependencies = [
        ('reviewers', '0012_autoapprovalsummary_score'),
        # Need a recent enough migration to have score and version in ScannerResult
        ('scanners', '0037_auto_20200717_1233'),
        ('addons', '0002_addon_fk'),  # Need addon___current_version to exist
    ]

    operations = [
        migrations.RunPython(forwards_func, reverse_func),
    ]
