from django.core.cache import cache
from django.db.transaction import non_atomic_requests
from django.template.response import TemplateResponse
from django.utils.cache import patch_cache_control
from django.utils.translation import gettext

from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.status import HTTP_201_CREATED, HTTP_202_ACCEPTED
from rest_framework.views import APIView

from olympia import amo
from olympia.api.authentication import JWTKeyAuthentication
from olympia.amo.feeds import BaseFeed
from olympia.amo.templatetags.jinja_helpers import absolutify, url
from olympia.api.permissions import ByHttpMethod, GroupPermission
from olympia.versions.compare import version_dict, version_re

from .models import AppVersion


class AppVersionView(APIView):
    authentication_classes = [JWTKeyAuthentication]
    permission_classes = []
    permission_classes = [
        ByHttpMethod(
            {
                'get': AllowAny,
                'options': AllowAny,  # Needed for CORS.
                'put': GroupPermission(amo.permissions.APPVERSIONS_CREATE),
            }
        ),
    ]

    def get(self, request, *args, **kwargs):
        application = amo.APPS.get(kwargs.get('application'))
        if not application:
            raise ParseError('Invalid application parameter')
        versions = (
            AppVersion.objects.filter(application=application.id)
            .order_by('version_int')
            .values_list('version', flat=True)
        )
        response = Response(
            {
                'guid': application.guid,
                'versions': list(versions),
            }
        )
        patch_cache_control(response, max_age=60 * 60)
        return response

    def put(self, request, *args, **kwargs):
        # For each request, we'll try to create up to 3 versions for each app,
        # one for the parameter in the URL, one for the corresponding "release"
        # version if it's different (if 79.0a1 is passed, the base would be
        # 79.0. If 79.0 is passed, then we'd skip that one as they are the
        # same) and a last one for the corresponding max version with a star
        # (if 79.0 or 79.0a1 is passed, then this would be 79.*)
        # We validate the app parameter, but always try to create the versions
        # for both Firefox and Firefox for Android anyway, because at the
        # extension manifest level there is no difference so for validation
        # purposes we want to keep both in sync.
        application = amo.APPS.get(kwargs.get('application'))
        if not application:
            raise ParseError('Invalid application parameter')
        requested_version = kwargs.get('version')
        if not requested_version or not version_re.match(requested_version):
            raise ParseError('Invalid version parameter')
        version_data = version_dict(requested_version)
        release_version = '%d.%d' % (version_data['major'], version_data['minor1'] or 0)
        star_version = '%d.*' % version_data['major']
        created_firefox = self.create_versions_for_app(
            application=amo.FIREFOX,
            requested_version=requested_version,
            release_version=release_version,
            star_version=star_version,
        )
        created_android = self.create_versions_for_app(
            application=amo.ANDROID,
            requested_version=requested_version,
            release_version=release_version,
            star_version=star_version,
        )
        created = created_firefox or created_android
        status_code = HTTP_201_CREATED if created else HTTP_202_ACCEPTED
        return Response(status=status_code)

    def create_versions_for_app(
        self, *, application, requested_version, release_version, star_version
    ):
        _, created_requested = AppVersion.objects.get_or_create(
            application=application.id, version=requested_version
        )
        if requested_version != release_version:
            _, created_release = AppVersion.objects.get_or_create(
                application=application.id, version=release_version
            )
        else:
            created_release = False
        if requested_version != star_version:
            _, created_star = AppVersion.objects.get_or_create(
                application=application.id, version=star_version
            )
        else:
            created_star = False
        return created_requested or created_release or created_star
