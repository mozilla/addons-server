import collections
import os
import re
import sys
import textwrap
import traceback
from datetime import datetime
from itertools import chain
from urlparse import urljoin

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection
from django.db.models import Sum
from django.template import Context, Template
from django.utils import translation

import requests

import olympia.core.logger
from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonCategory, AddonUser, Category
from olympia.amo.celery import task
from olympia.amo.decorators import write
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import chunked, send_mail, sorted_groupby
from olympia.constants.categories import CATEGORIES
from olympia.devhub.tasks import run_validator
from olympia.files.models import FileUpload
from olympia.files.utils import parse_addon
from olympia.lib.crypto.packaged import sign_file
from olympia.users.models import UserProfile
from olympia.users.utils import get_task_user
from olympia.versions.models import License, Version
from olympia.zadmin.models import (
    EmailPreviewTopic, ValidationJob, ValidationResult)

log = olympia.core.logger.getLogger('z.task')


@task(rate_limit='3/s')
def admin_email(all_recipients, subject, body, preview_only=False,
                from_email=settings.DEFAULT_FROM_EMAIL,
                preview_topic='admin_email', **kw):
    log.info('[%s@%s] admin_email about %r'
             % (len(all_recipients), admin_email.rate_limit, subject))
    if preview_only:
        send = EmailPreviewTopic(topic=preview_topic).send_mail
    else:
        send = send_mail
    for recipient in all_recipients:
        send(subject, body, recipient_list=[recipient], from_email=from_email)


def tally_job_results(job_id, **kw):
    sql = """select sum(1),
                    sum(case when completed IS NOT NULL then 1 else 0 end)
             from validation_result
             where validation_job_id=%s"""

    with connection.cursor() as cursor:
        cursor.execute(sql, [job_id])
        total, completed = cursor.fetchone()

    if completed == total:
        # The job has finished.
        job = ValidationJob.objects.get(pk=job_id)
        job.update(completed=datetime.now())
        if job.finish_email:
            send_mail(u'Behold! Validation results for %s %s->%s'
                      % (amo.APP_IDS[job.application].pretty,
                         job.curr_max_version.version,
                         job.target_version.version),
                      textwrap.dedent("""
                          Aww yeah
                          %s
                          """ % absolutify(reverse('zadmin.validation'))),
                      from_email=settings.DEFAULT_FROM_EMAIL,
                      recipient_list=[job.finish_email])


@task(rate_limit='6/s')
@write
def bulk_validate_file(result_id, **kw):
    res = ValidationResult.objects.get(pk=result_id)
    task_error = None
    validation = None
    file_base = os.path.basename(res.file.file_path)
    try:
        log.info('[1@None] Validating file %s (%s) for result_id %s'
                 % (res.file, file_base, res.id))
        target = res.validation_job.target_version
        guid = amo.APP_IDS[target.application].guid
        ver = {guid: [target.version]}
        # Set min/max so the validator only tests for compatibility with
        # the target version. Note that previously we explicitly checked
        # for compatibility with older versions. See bug 675306 for
        # the old behavior.
        overrides = {'targetapp_minVersion': {guid: target.version},
                     'targetapp_maxVersion': {guid: target.version}}
        validation = run_validator(res.file.file_path, for_appversions=ver,
                                   test_all_tiers=True, overrides=overrides,
                                   compat=True)
    except:
        task_error = sys.exc_info()
        log.exception(
            u'bulk_validate_file exception on file {} ({})'
            .format(res.file, file_base))

    res.completed = datetime.now()
    if task_error:
        res.task_error = ''.join(traceback.format_exception(*task_error))
    else:
        res.apply_validation(validation)
        log.info('[1@None] File %s (%s) errors=%s'
                 % (res.file, file_base, res.errors))
    res.save()
    tally_job_results(res.validation_job.id)


@task
@write
def add_validation_jobs(pks, job_pk, **kw):
    log.info('[%s@None] Adding validation jobs for addons starting at: %s '
             ' for job: %s'
             % (len(pks), pks[0], job_pk))

    job = ValidationJob.objects.get(pk=job_pk)
    curr_ver = job.curr_max_version.version_int
    target_ver = job.target_version.version_int
    unreviewed_statuses = (amo.STATUS_AWAITING_REVIEW, amo.STATUS_BETA)
    for addon in Addon.objects.filter(pk__in=pks):
        ids = set()
        base = addon.versions.filter(apps__application=job.application,
                                     apps__max__version_int__gte=curr_ver,
                                     apps__max__version_int__lt=target_ver,
                                     channel=amo.RELEASE_CHANNEL_LISTED)

        already_compat = addon.versions.filter(
            channel=amo.RELEASE_CHANNEL_LISTED,
            files__status=amo.STATUS_PUBLIC,
            apps__max__version_int__gte=target_ver)
        if already_compat.exists():
            log.info('Addon %s already has a public version %r which is '
                     'compatible with target version of app %s %s (or newer)'
                     % (addon.pk, [v.pk for v in already_compat.all()],
                        job.application, job.target_version))
            continue

        try:
            public = (base.filter(files__status=amo.STATUS_PUBLIC)
                          .latest('id'))
        except ObjectDoesNotExist:
            public = None

        if public:
            ids.update([f.id for f in public.files.all()])
            ids.update(base.filter(files__status__in=unreviewed_statuses,
                                   id__gt=public.id)
                           .values_list('files__id', flat=True))

        else:
            ids.update(base.filter(files__status__in=unreviewed_statuses)
                       .values_list('files__id', flat=True))

        log.info('Adding %s files for validation for '
                 'addon: %s for job: %s' % (len(ids), addon.pk, job_pk))
        for id in ids:
            result = ValidationResult.objects.create(validation_job_id=job_pk,
                                                     file_id=id)
            bulk_validate_file.delay(result.pk)


def get_context(addon, version, job, results, fileob=None):
    result_links = (absolutify(reverse('devhub.bulk_compat_result',
                                       args=[addon.slug, r.pk]))
                    for r in results)
    addon_name = addon.name
    if fileob and fileob.platform != amo.PLATFORM_ALL.id:
        addon_name = u'%s (%s)' % (addon_name, fileob.get_platform_display())
    return {
        'ADDON_NAME': addon_name,
        'ADDON_VERSION': version.version,
        'APPLICATION': str(job.application),
        'COMPAT_LINK': absolutify(reverse('devhub.versions.edit',
                                          args=[addon.pk, version.pk])),
        'RESULT_LINKS': ' '.join(result_links),
        'VERSION': job.target_version.version
    }


@task
@write
def update_maxversions(version_pks, job_pk, data, **kw):
    log.info('[%s@%s] Updating max version for job %s.'
             % (len(version_pks), update_maxversions.rate_limit, job_pk))
    job = ValidationJob.objects.get(pk=job_pk)
    core.set_user(get_task_user())
    dry_run = data['preview_only']
    app_id = job.target_version.application
    stats = collections.defaultdict(int)
    stats['processed'] = 0
    stats['is_dry_run'] = int(dry_run)
    for version in Version.objects.filter(pk__in=version_pks):
        stats['processed'] += 1
        file_pks = version.files.values_list('pk', flat=True)
        errors = (ValidationResult.objects.filter(validation_job=job,
                                                  file__pk__in=file_pks)
                                          .values_list('errors', flat=True))
        if any(errors):
            stats['invalid'] += 1
            log.info('Version %s for addon %s not updated, '
                     'one of the files did not pass validation'
                     % (version.pk, version.addon.pk))
            continue

        for app in version.apps.filter(
                application=job.curr_max_version.application,
                max__version_int__gte=job.curr_max_version.version_int,
                max__version_int__lt=job.target_version.version_int):
            stats['bumped'] += 1
            log.info('Updating version %s%s for addon %s from version %s '
                     'to version %s'
                     % (version.pk,
                        ' [DRY RUN]' if dry_run else '',
                        version.addon.pk,
                        job.curr_max_version.version,
                        job.target_version.version))
            app.max = job.target_version
            if not dry_run:
                app.save()
                ActivityLog.create(
                    amo.LOG.MAX_APPVERSION_UPDATED,
                    version.addon, version,
                    details={'version': version.version,
                             'target': job.target_version.version,
                             'application': app_id})

    log.info('[%s@%s] bulk update stats for job %s: {%s}'
             % (len(version_pks), update_maxversions.rate_limit, job_pk,
                ', '.join('%s: %s' % (k, stats[k])
                          for k in sorted(stats.keys()))))


def _completed_versions(job, prefix=''):
    filter = dict(files__validation_results__validation_job=job,
                  files__validation_results__completed__isnull=False)
    if not prefix:
        return filter

    res = {}
    for k, v in filter.iteritems():
        res['%s__%s' % (prefix, k)] = v
    return res


def updated_versions(job):
    return (
        Version.objects
        .filter(files__validation_results__validation_job=job,
                files__validation_results__errors=0,
                files__validation_results__completed__isnull=False,
                apps__application=job.curr_max_version.application,
                apps__max__version_int__gte=job.curr_max_version.version_int,
                apps__max__version_int__lt=job.target_version.version_int)
        .exclude(files__validation_results__errors__gt=0)
        .values_list('pk', flat=True).distinct())


def completed_version_authors(job):
    return (
        Version.objects
        .filter(**_completed_versions(job))
        # Prevent sorting by version creation date and
        # thereby breaking `.distinct()`.
        .order_by('addon__authors__pk')
        .values_list('addon__authors__pk', flat=True).distinct())


@task
def notify_compatibility(job, params):
    dry_run = params['preview_only']

    log.info('[@None] Starting validation email/update process for job %d.'
             ' dry_run=%s.' % (job.pk, dry_run))

    log.info('[@None] Starting validation version bumps for job %d.' % job.pk)

    version_list = updated_versions(job)
    total = version_list.count()

    for chunk in chunked(version_list, 100):
        log.info('[%d@%d] Updating versions for job %d.' % (
            len(chunk), total, job.pk))
        update_maxversions.delay(chunk, job.pk, params)

    log.info('[@None] Starting validation email run for job %d.' % job.pk)

    updated_authors = completed_version_authors(job)
    total = updated_authors.count()
    for chunk in chunked(updated_authors, 100):
        log.info('[%d@%d] Notifying authors for validation job %d'
                 % (len(chunk), total, job.pk))

        # There are times when you want to punch django's ORM in
        # the face. This may be one of those times.
        users_addons = list(
            UserProfile.objects.filter(pk__in=chunk)
                       .filter(**_completed_versions(job,
                                                     'addons__versions'))
                       .values_list('pk', 'addons__pk').distinct())

        users = list(UserProfile.objects.filter(
                     pk__in=set(u for u, a in users_addons)))

        # Annotate fails in tests when using cached results
        addons = (Addon.objects.no_cache()
                  .filter(**{
                      'pk__in': set(a for u, a in users_addons),
                      'versions__files__'
                      'validation_results__validation_job': job
                  })
                  .annotate(errors=Sum(
                      'versions__files__validation_results__errors')))
        addons = dict((a.id, a) for a in addons)

        users_addons = dict((u, [addons[a] for u, a in row])
                            for u, row in sorted_groupby(users_addons,
                                                         lambda k: k[0]))

        log.info('[%d@%d] Notifying %d authors about %d addons for '
                 'validation job %d'
                 % (len(chunk), total, len(users), len(addons.keys()), job.pk))

        for u in users:
            addons = users_addons[u.pk]

            u.passing_addons = [a for a in addons if a.errors == 0]
            u.failing_addons = [a for a in addons if a.errors > 0]

        notify_compatibility_chunk.delay(users, job, params)

    log.info('[@None] Completed validation email/update process '
             'for job %d. dry_run=%s.' % (job.pk, dry_run))


@task
@write
def notify_compatibility_chunk(users, job, data, **kw):
    log.info('[%s@%s] Sending notification mail for job %s.'
             % (len(users), notify_compatibility.rate_limit, job.pk))
    core.set_user(get_task_user())
    dry_run = data['preview_only']
    app_id = job.target_version.application
    stats = collections.defaultdict(int)
    stats['processed'] = 0
    stats['is_dry_run'] = int(dry_run)

    for user in users:
        stats['processed'] += 1

        try:
            for addon in chain(user.passing_addons, user.failing_addons):
                try:
                    results = job.result_set.filter(file__version__addon=addon)

                    addon.links = [
                        absolutify(reverse('devhub.bulk_compat_result',
                                           args=[addon.slug, r.pk]))
                        for r in results]

                    version = (
                        addon.current_version or addon.find_latest_version(
                            channel=amo.RELEASE_CHANNEL_LISTED))
                    addon.compat_link = absolutify(reverse(
                        'devhub.versions.edit', args=[addon.pk, version.pk]))
                except:
                    task_error = sys.exc_info()
                    log.error(u'Bulk validation email error for user %s, '
                              u'addon %s: %s: %s'
                              % (user.email, addon.slug,
                                 task_error[0], task_error[1]), exc_info=False)

            context = Context({
                'APPLICATION': unicode(amo.APP_IDS[job.application].pretty),
                'VERSION': job.target_version.version,
                'PASSING_ADDONS': user.passing_addons,
                'FAILING_ADDONS': user.failing_addons,
            })

            log.info(u'Emailing %s%s for %d addons about '
                     'bulk validation job %s'
                     % (user.email,
                        ' [PREVIEW]' if dry_run else '',
                        len(user.passing_addons) + len(user.failing_addons),
                        job.pk))
            args = (Template(data['subject']).render(context),
                    Template(data['text']).render(context))
            kwargs = dict(from_email=settings.DEFAULT_FROM_EMAIL,
                          recipient_list=[user.email])
            if dry_run:
                job.preview_notify_mail(*args, **kwargs)
            else:
                stats['author_emailed'] += 1
                send_mail(*args, **kwargs)
                ActivityLog.create(
                    amo.LOG.BULK_VALIDATION_USER_EMAILED,
                    user,
                    details={'passing': [a.id for a in user.passing_addons],
                             'failing': [a.id for a in user.failing_addons],
                             'target': job.target_version.version,
                             'application': app_id})
        except:
            task_error = sys.exc_info()
            log.error(u'Bulk validation email error for user %s: %s: %s'
                      % (user.email,
                         task_error[0], task_error[1]), exc_info=False)

    log.info('[%s@%s] bulk email stats for job %s: {%s}'
             % (len(users), notify_compatibility.rate_limit, job.pk,
                ', '.join('%s: %s' % (k, stats[k])
                          for k in sorted(stats.keys()))))


@task
def fetch_langpacks(path, **kw):
    log.info('[@None] Fetching language pack updates {0}'.format(path))

    # Treat `path` as relative even if it begins with a leading /
    base_url = urljoin(settings.LANGPACK_DOWNLOAD_BASE,
                       './' + path.strip('/') + '/')

    # Find the checksum manifest, 2 directories up.
    list_url = urljoin(base_url, settings.LANGPACK_MANIFEST_PATH)
    list_base = urljoin(list_url, './')

    log.info('[@None] Fetching language pack manifests from {0}'
             .format(list_url))

    if not list_url.startswith(settings.LANGPACK_DOWNLOAD_BASE):
        log.error('[@None] Not fetching language packs from invalid URL: '
                  '{0}'.format(base_url))
        raise ValueError('Invalid path')

    try:
        req = requests.get(list_url,
                           verify=settings.CA_CERT_BUNDLE_PATH)
    except Exception, e:
        log.error('[@None] Error fetching language pack list {0}: {1}'
                  .format(path, e))
        return

    xpi_list = [urljoin(list_base, line[-1])
                for line in map(str.split, req.iter_lines())]

    allowed_file = re.compile(r'^[A-Za-z-]+\.xpi$').match

    for url in xpi_list:
        # Filter out files not in the target langpack directory.
        if not url.startswith(base_url):
            continue

        xpi = url[len(base_url):]
        # Filter out entries other than direct child XPIs.
        if not allowed_file(xpi):
            continue

        fetch_langpack.delay(url, xpi)


@task(rate_limit='6/s')
@write
def fetch_langpack(url, xpi, **kw):
    try:
        req = requests.get(url,
                           verify=settings.CA_CERT_BUNDLE_PATH)

        if ('content-length' not in req.headers or
            int(req.headers['content-length']) >
                settings.LANGPACK_MAX_SIZE):
            log.error('[@None] Language pack "{0}" too large: {1} > {2}'
                      .format(xpi, req.headers['content-large'],
                              settings.LANGPACK_MAX_SIZE))
            return

        chunks = []
        size = 0
        for chunk in req.iter_content(settings.LANGPACK_MAX_SIZE):
            size += len(chunk)
            # `requests` doesn't respect the Content-Length header
            # so we need to check twice.
            if size > settings.LANGPACK_MAX_SIZE:
                raise Exception('Response to big')
            chunks.append(chunk)
    except Exception, e:
        log.error('[@None] Error fetching "{0}" language pack: {1}'
                  .format(xpi, e))
        return

    upload = FileUpload()
    upload.add_file(chunks, xpi, size)

    lang = os.path.splitext(xpi)[0]

    # Activate the correct locale for the language pack so it
    # will be used as the add-on's default locale if available.
    with translation.override(lang):
        try:
            data = parse_addon(upload, check=False)

            allowed_guid = re.compile(r'^langpack-{0}@'
                                      r'[a-z]+\.mozilla\.org$'.format(lang))
            assert allowed_guid.match(data['guid']), 'Unexpected GUID'
        except Exception, e:
            log.error('[@None] Error parsing "{0}" language pack: {1}'
                      .format(xpi, e),
                      exc_info=sys.exc_info())
            return

        try:
            addon = Addon.objects.get(guid=data['guid'])
        except Addon.DoesNotExist:
            addon = None

        try:
            # Parse again now that we have the add-on.
            data = parse_addon(upload, addon)
        except Exception, e:
            log.error('[@None] Error parsing "{0}" language pack: {1}'
                      .format(xpi, e),
                      exc_info=sys.exc_info())
            return

        if not data['apps']:
            # We don't have the app versions that the langpack specifies
            # in our approved versions list. Don't create a version for it,
            # so we can retry once they've been added.
            log.error('[@None] Not creating langpack {guid} {version} because '
                      'it has no valid compatible apps.'.format(**data))
            return

        is_beta = amo.VERSION_BETA.search(data['version'])
        owner = UserProfile.objects.get(email=settings.LANGPACK_OWNER_EMAIL)

        if addon:
            if addon.versions.filter(version=data['version']).exists():
                log.info('[@None] Version {0} of "{1}" language pack exists'
                         .format(data['version'], xpi))
                return

            if not addon.addonuser_set.filter(user=owner).exists():
                log.info('[@None] Skipping language pack "{0}": '
                         'not owned by {1}'.format(
                             xpi, settings.LANGPACK_OWNER_EMAIL))
                return

            version = Version.from_upload(upload, addon, [amo.PLATFORM_ALL.id],
                                          amo.RELEASE_CHANNEL_LISTED,
                                          is_beta=is_beta)

            log.info('[@None] Updated language pack "{0}" to version {1}'
                     .format(xpi, data['version']))
        else:
            if is_beta:
                log.error('[@None] Not creating beta version {0} for new '
                          '"{1}" language pack'.format(data['version'], xpi))
                return

            if (Addon.objects.filter(name__localized_string=data['name'])
                    .exists()):
                data['old_name'] = data['name']
                data['name'] = u'{0} ({1})'.format(
                    data['old_name'], data['apps'][0].appdata.pretty)

                log.warning(u'[@None] Creating langpack {guid}: Add-on with '
                            u'name {old_name!r} already exists, trying '
                            u'{name!r}.'.format(**data))

            addon = Addon.from_upload(
                upload, [amo.PLATFORM_ALL.id], parsed_data=data)
            AddonUser(addon=addon, user=owner).save()
            version = addon.versions.get()

            if addon.default_locale.lower() == lang.lower():
                addon.target_locale = addon.default_locale

            addon.save()

            log.info('[@None] Created new "{0}" language pack, version {1}'
                     .format(xpi, data['version']))

        # Set the category
        for app in version.compatible_apps:
            static_category = (
                CATEGORIES.get(app.id, []).get(amo.ADDON_LPAPP, [])
                .get('general'))
            if static_category:
                category = Category.from_static_category(static_category, True)
                AddonCategory.objects.get_or_create(
                    addon=addon, category=category)

        # Add a license if there isn't one already
        if not version.license:
            license = License.objects.builtins().get(builtin=1)
            version.update(license=license)

        file_ = version.files.get()
        if not is_beta:
            # Not `version.files.update`, because we need to trigger save
            # hooks.
            file_.update(status=amo.STATUS_PUBLIC)
        sign_file(file_, settings.SIGNING_SERVER)

        # Finally, set the addon summary if one wasn't provided in the xpi.
        addon.status = amo.STATUS_PUBLIC
        addon.summary = addon.summary if addon.summary else unicode(addon.name)
        addon.save(update_fields=('status', 'summary'))
        addon.update_status()


@task
def celery_error(**kw):
    """
    This task raises an exception from celery to test error logging and
    Sentry hookup.
    """
    log.info('about to raise an exception from celery')
    raise RuntimeError('this is an exception from celery')
