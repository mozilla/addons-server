import logging
import shutil
from datetime import datetime

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage

from rest_framework import status
from rest_framework.response import Response
from tower import ugettext as _

import amo
from access import acl
from addons.models import Addon, AddonUser
from amo.decorators import use_master
from api.jwt_auth.views import JWTProtectedView
from devhub.views import handle_upload
from files.models import File, FileUpload
from files.utils import parse_addon, update_version_number
from lib.crypto.packaged import sign_file
from versions import views as version_views
from versions.compare import version_int
from versions.models import Version
from signing.serializers import FileUploadSerializer

log = logging.getLogger('signing')


def with_addon(allow_missing=False):
    """Call the view function with an addon instead of a guid. This will try
    find an addon with the guid and verify the user's permissions. If the
    add-on is not found it will 404 when allow_missing is False otherwise it
    will call the view with addon set to None."""
    def wrapper(fn):
        def inner(view, request, guid=None, **kwargs):
            try:
                addon = Addon.unfiltered.get(guid=guid)
            except Addon.DoesNotExist:
                if allow_missing:
                    addon = None
                else:
                    return Response({'error': _('Could not find add-on with '
                                                'id "{}".'.format(guid))},
                                    status=status.HTTP_404_NOT_FOUND)
            if addon is not None and not addon.has_author(request.user):
                return Response(
                    {'error': _('You do not own this addon.')},
                    status=status.HTTP_403_FORBIDDEN)
            return fn(view, request, addon=addon, **kwargs)
        return inner
    return wrapper


class VersionView(JWTProtectedView):

    @with_addon(allow_missing=True)
    def put(self, request, addon, version_string):
        if 'upload' in request.FILES:
            filedata = request.FILES['upload']
        else:
            return Response(
                {'error': _('Missing "upload" key in multipart file data.')},
                status=status.HTTP_400_BAD_REQUEST)

        try:
            # Parse the file to get and validate package data with the addon.
            pkg = parse_addon(filedata, addon)
            if not acl.submission_allowed(request.user, pkg):
                raise forms.ValidationError(
                    _(u'You cannot submit this type of add-on'))
        except forms.ValidationError as e:
            return Response({'error': e.message},
                            status=status.HTTP_400_BAD_REQUEST)
        if pkg['version'] != version_string:
            return Response(
                {'error': _('Version does not match install.rdf.')},
                status=status.HTTP_400_BAD_REQUEST)
        elif (addon is not None and
                addon.versions.filter(
                    version=version_string,
                    files__status__in=amo.REVIEWED_STATUSES).exists()):
            return Response({'error': _('Version already exists.')},
                            status=status.HTTP_409_CONFLICT)

        if addon is None:
            addon = Addon.create_addon_from_upload_data(
                data=pkg, user=request.user, is_listed=False)
            status_code = status.HTTP_201_CREATED
        else:
            status_code = status.HTTP_202_ACCEPTED

        file_upload = handle_upload(
            filedata=filedata, user=request.user, addon=addon, submit=True)

        return Response(FileUploadSerializer(file_upload).data,
                        status=status_code)

    @use_master
    @with_addon()
    def get(self, request, addon, version_string, pk=None):
        file_upload_qs = FileUpload.objects.filter(
            addon=addon, version=version_string)
        try:
            if pk is None:
                file_upload = file_upload_qs.latest()
                log.info('getting latest upload for {addon} {version}: '
                         '{file_upload.pk}'.format(
                             addon=addon, version=version_string,
                             file_upload=file_upload))
            else:
                file_upload = file_upload_qs.get(pk=pk)
                log.info('getting specific upload for {addon} {version} {pk}: '
                         '{file_upload.pk}'.format(
                             addon=addon, version=version_string, pk=pk,
                             file_upload=file_upload))
        except FileUpload.DoesNotExist:
            return Response(
                {'error': _('No uploaded file for that addon and version.')},
                status=status.HTTP_404_NOT_FOUND)

        try:
            version = addon.versions.filter(version=version_string).latest()
        except Version.DoesNotExist:
            version = None

        serializer = FileUploadSerializer(file_upload, version=version)
        return Response(serializer.data)


REPACK_MAIL_SUBJECT = u'Mozilla Add-ons: {addon} has been repacked on AMO'
REPACK_MAIL_MESSAGE = u"""
Your add-on, {addon}, has been automatically repacked.
{repack_reason}
We recommend that you give it a try to make sure it doesn't have any unexpected
problems: {addon_url}

If you have any questions or comments on this, please reply to this email or
join #amo-editors on irc.mozilla.org.

You're receiving this email because you have an add-on hosted on
https://addons.mozilla.org
"""


class SignedFile(JWTProtectedView):

    @use_master
    def get(self, request, file_id):
        return version_views.download_file(request, file_id)

    def post(self, request, file_id):
        """Repack: overwrite a File's filesystem file, bump its version number.

        This is a POST, not a PUT: it's going to modify the current File, not
        create a new one.
        When uploaded:
            - the new file's GUID will be compared to the add-on GUID
            - the current file will be backuped
            - the version number in the new file's manifest will be bumped
            - the new file will be re-signed if `File.is_signed is True`
            - the `Version.version` number will also be bumped
            - send an email to the add-on author
        """
        # Is the user allowed to use this API?
        if not acl.action_allowed_user(request.user, 'Addons', 'Edit'):
            return Response(
                {'error': _('You are not allowed to use this API endpoint.')},
                status=status.HTTP_403_FORBIDDEN)

        try:
            file_ = File.objects.get(pk=file_id)
        except File.DoesNotExist:
            return Response(
                {'error': _('No file found with id {}').format(file_id)},
                status=status.HTTP_404_NOT_FOUND)

        if 'upload' in request.FILES:
            filedata = request.FILES['upload']
        else:
            return Response(
                {'error': _('Missing "upload" key in multipart file data.')},
                status=status.HTTP_400_BAD_REQUEST)

        if 'repack_reason' in request.DATA:
            repack_reason = '\n{}\n'.format(request.DATA['repack_reason'])
        else:
            return Response(
                {'error': _('Missing "repack_reason" key in post data.')},
                status=status.HTTP_400_BAD_REQUEST)

        addon = file_.version.addon
        try:
            # Parse the file to get and validate package data with the addon.
            pkg = parse_addon(filedata, addon)
        except forms.ValidationError as e:
            return Response(
                {'error': e.message},
                status=status.HTTP_403_FORBIDDEN)

        log.info(u'Starting repack for file {file_id}'.format(file_id=file_id))
        # Backup the file.
        suffix = 'repack-{}'.format(datetime.now().strftime('%Y%m%d%H%M%S'))
        backuped_filename = '{filename}.{suffix}'.format(
            filename=file_.file_path, suffix=suffix)
        shutil.copy(file_.file_path, backuped_filename)
        log.info(u'File {file_id} backuped to {path}'.format(
            file_id=file_id, path=backuped_filename))

        # Overwrite the current file.
        file_upload = handle_upload(
            filedata=filedata, user=request.user, addon=addon, submit=False)
        with storage.open(file_.file_path, 'wb') as fd:
            for chunk in filedata:
                fd.write(chunk)

        # Bump the version number in the package.
        version_number = pkg['version']
        bumped_version_number = '{version_number}.1-{suffix}'.format(
            version_number=version_number, suffix=suffix)
        log.info(u'Bumping version number for file {file_id} to {version}'
                 .format(file_id=file_id, version=bumped_version_number))
        update_version_number(file_, bumped_version_number)

        # Re-sign the file now that it's been repacked and bumped (if needed).
        if file_.is_signed:
            log.info(u'Re-signing file {file_id}'.format(file_id=file_id))
            if file_.status == amo.STATUS_PUBLIC:
                server = settings.SIGNING_SERVER
            else:
                server = settings.PRELIMINARY_SIGNING_SERVER
            sign_file(file_, server)

        # Bump the version number in the Version model.
        log.info(u'Bump Version.version number for version {version_id} to '
                 u'{version}'.format(
                     version_id=file_.version.pk,
                     version=bumped_version_number))
        file_.version.update(version=bumped_version_number,
                             version_int=version_int(bumped_version_number))

        # Send a mail to the owners/devs warning them we've automatically
        # repacked their addon.
        qs = (AddonUser.objects
              .filter(role=amo.AUTHOR_ROLE_OWNER, addon=addon)
              .exclude(user__email__isnull=True))
        emails = qs.values_list('user__email', flat=True)
        subject = REPACK_MAIL_SUBJECT.format(addon=addon.name)

        log.info(u'Sending "repack reason" by email to {users}'.format(
                 users=', '.join(emails)))
        message = REPACK_MAIL_MESSAGE.format(
            addon=addon.name,
            addon_url=amo.helpers.absolutify(
                addon.get_dev_url(action='versions')),
            repack_reason=repack_reason)
        amo.utils.send_mail(
            subject, message, recipient_list=emails,
            fail_silently=True,
            headers={'Reply-To': 'amo-editors@mozilla.org'})

        return Response(FileUploadSerializer(file_upload).data,
                        status=status.HTTP_202_ACCEPTED)
