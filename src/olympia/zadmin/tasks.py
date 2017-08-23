import os
import re
import sys
import textwrap
import traceback
from datetime import datetime
from urlparse import urljoin

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection
from django.utils import translation

import requests

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon, AddonCategory, AddonUser, Category
from olympia.amo.celery import task
from olympia.amo.decorators import write
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import send_mail
from olympia.constants.categories import CATEGORIES
from olympia.devhub.tasks import run_validator
from olympia.files.models import FileUpload
from olympia.files.utils import parse_addon
from olympia.lib.crypto.packaged import sign_file
from olympia.users.models import UserProfile
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
