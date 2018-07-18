import json

import requests

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

import olympia.core.logger

from olympia.files.models import FileUpload
from olympia.github.tasks import process_webhook
from olympia.github.utils import GithubCallback, GithubRequest


log = olympia.core.logger.getLogger('z.github')


class GithubView(APIView):
    def post(self, request):
        if request.META.get('HTTP_X_GITHUB_EVENT') != 'pull_request':
            # That's ok, we are just going to ignore it, we'll return a 2xx
            # response so github doesn't report it as an error.
            return Response({}, status=status.HTTP_200_OK)

        # If the content-type is form-urlencoded the JSON is sent in the
        # payload parameter.
        #
        # See: https://developer.github.com/webhooks/creating/#content-type
        if (
            request.META.get('CONTENT_TYPE')
            == 'application/x-www-form-urlencoded'
        ):
            data = json.loads(request.data['payload'])
        else:
            data = request.data

        github = GithubRequest(data=data)
        if not github.is_valid():
            return Response({}, status=422)

        data = github.cleaned_data
        upload = FileUpload.objects.create()
        log.info('Created FileUpload from github api: {}'.format(upload.pk))

        try:
            github = GithubCallback(data)
            github.pending()
        except requests.HTTPError as err:
            # This is a common error, where the user hasn't set up add-ons
            # robot as a contributor, so we'll get a 404 from GitHub. Let's
            # try and get a nice error message back into the GitHub UI.
            if err.response.status_code == status.HTTP_404_NOT_FOUND:
                return Response(
                    {
                        'details': (
                            'Writing pending status failed. Please ensure '
                            'the addons.mozilla.org GitHub account has write '
                            'access to this repository.'
                        )
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

        process_webhook.delay(upload.pk, data)
        return Response({}, status=status.HTTP_201_CREATED)
