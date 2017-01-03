import commonware

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from olympia.files.models import FileUpload
from olympia.github.tasks import process_webhook
from olympia.github.utils import GithubRequest, GithubCallback

log = commonware.log.getLogger('z.github')


class GithubView(APIView):

    def post(self, request):
        if request.META.get('HTTP_X_GITHUB_EVENT') != 'pull_request':
            # That's ok, we are just going to ignore it, we'll return a 2xx
            # response so github doesn't report it as an error.
            return Response({}, status=status.HTTP_200_OK)

        github = GithubRequest(data=request.data)
        if not github.is_valid():
            return Response({}, status=422)

        data = github.cleaned_data
        upload = FileUpload.objects.create()
        log.info('Created FileUpload from github api: {}'.format(upload.pk))
        github = GithubCallback(data)
        github.pending()

        process_webhook.delay(upload.pk, data)
        return Response({}, status=status.HTTP_201_CREATED)
