import re

from django.conf import settings
from django.utils import translation

import requests

from requests.exceptions import RequestException

import olympia.core.logger

from olympia.amo.celery import task
from olympia.amo.decorators import write
from olympia.files.models import (
    File, WebextPermission, WebextPermissionDescription)
from olympia.files.utils import parse_xpi
from olympia.translations.models import Translation
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.files.task')


@task
@write
def extract_webext_permissions(ids, **kw):
    log.info('[%s@%s] Extracting permissions from Files, starting at id: %s...'
             % (len(ids), extract_webext_permissions.rate_limit, ids[0]))
    files = File.objects.filter(pk__in=ids).no_transforms()

    # A user needs to be passed down to parse_xpi(), so we use the task user.
    user = UserProfile.objects.get(pk=settings.TASK_USER_ID)

    for file_ in files:
        try:
            log.info('Parsing File.id: %s @ %s' %
                     (file_.pk, file_.current_file_path))
            parsed_data = parse_xpi(file_.current_file_path, user=user)
            permissions = parsed_data.get('permissions', [])
            # Add content_scripts host matches too.
            for script in parsed_data.get('content_scripts', []):
                permissions.extend(script.get('matches', []))
            if permissions:
                log.info('Found %s permissions for: %s' %
                         (len(permissions), file_.pk))
                WebextPermission.objects.update_or_create(
                    defaults={'permissions': permissions}, file=file_)
        except Exception, err:
            log.error('Failed to extract: %s, error: %s' % (file_.pk, err))


WEBEXTPERMS_DESCRIPTION_REGEX = r'^webextPerms\.description\.(.+)=(.+)'


@task
@write
def update_webext_descriptions_all(primary, additional, **kw):
    """primary is a (url, locale) tuple; additional is a list of tuples."""
    url, locale = primary
    update_webext_descriptions(url, locale)
    for url, locale in additional:
        update_webext_descriptions(url, locale, create=False)


def update_webext_descriptions(url, locale='en-US', create=True, **kw):
    class DummyContextManager(object):
        def __enter__(self):
            pass

        def __exit__(*x):
            pass

    log.info('Updating webext permission descriptions in [%s] from %s' %
             (locale, url))
    try:
        response = requests.get(url)
        response.raise_for_status()
    except RequestException as e:
        log.warning('Error retrieving %s: %s' % (url, e))
        return

    # We only need to activate the locale for creating new permission objects.
    context = translation.override(locale) if create else DummyContextManager()
    with context:
        for line in response.text.splitlines():
            match = re.match(WEBEXTPERMS_DESCRIPTION_REGEX, line)
            if match:
                (perm, description) = match.groups()
                description = description.replace('%S', u'Firefox')
                if create:
                    log.info(u'Adding permission "%s" = "%s"' %
                             (perm, description))
                    WebextPermissionDescription.objects.update_or_create(
                        name=perm, defaults={'description': description})
                else:
                    log.info(u'Updating permission "%s" = "%s" for [%s]' %
                             (perm, description, locale))
                    try:
                        perm_obj = WebextPermissionDescription.objects.get(
                            name=perm)
                        Translation.objects.update_or_create(
                            id=perm_obj.description_id, locale=locale.lower(),
                            defaults={'localized_string': description})
                    except WebextPermissionDescription.DoesNotExist:
                        log.warning('No "%s" permission found to update with '
                                    '[%s] locale' % (perm, locale))
