from applications.models import Application


def run():
    Application.objects.create(
        id=61, guid='{aa3c5121-dab2-40e2-81ca-7ea25febc110}'
    )
