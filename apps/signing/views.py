from rest_framework.views import APIView


class AddonView(APIView):

    # Check the status of an existing addon
    def get(self, request):
        pass

    # Creates a new addon version
    def put(self, request):
        pass


class KeyView(APIView):

    def post(self, request):
        pass

    def delete(self, request):
        pass

    def get(self, request):
        pass
