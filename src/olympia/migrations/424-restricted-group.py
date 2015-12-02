from access.models import Group


def run():
    Group.objects.create(name='Restricted Users', rules='Restricted:UGC')
