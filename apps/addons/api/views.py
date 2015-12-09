from rest_framework import generics, serializers
from rest_framework.response import Response

from addons.models import Addon


class AddonSerializer(serializers.ModelSerializer):
    name = serializers.CharField()
    icon_url = serializers.CharField()

    class Meta:
        model = Addon
        fields = [
            'name',
            'slug',
            'icon_url',
            'id',
        ]


class SearchView(generics.RetrieveAPIView):
    serializer_class = AddonSerializer

    def retrieve(self, request, *args, **kwargs):
        queryset = Addon.objects.all()
        if 'q' in request.GET:
            queryset = queryset.filter(slug__contains=request.GET['q'])
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
