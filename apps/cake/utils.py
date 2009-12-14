from .models import Session


def handle_logout(request, response, **args):
    id = request.COOKIES.get('AMOv3')

    try:
        session = Session.objects.get(pk=id)
        session.delete()
    except Session.DoesNotExist:
        pass

    domain = request.META.get('HTTP_HOST')
    if domain and domain.find(':') != -1:
        parts = domain.split(':')
        domain = parts[0]


    response.delete_cookie('AMOv3', domain=domain)
