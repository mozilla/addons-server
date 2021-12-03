from django.db.transaction import non_atomic_requests
from django.utils.cache import patch_cache_control

from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Tag


class TagListView(APIView):
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        return Response(list(Tag.objects.values_list('tag_text', flat=True)))

    @classmethod
    def as_view(cls, **kwargs):
        view = super().as_view(**kwargs)
        return non_atomic_requests(view)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        patch_cache_control(response, max_age=60 * 60 * 6)
        return response
