from olympia.access.models import Group


GROUPS_TO_REMOVE = (
    'App Reviewer MOTD',
    'App Reviewers',
    'Bango Portal Viewers',
    'Carriers and Operators',
    'China Reviewers',
    'Feature Managers',
    'Marketplace Publishers',
    'Payment product icon clients',
    'Payment Testers',
    'Payment transactions clients',
    'Price currency manipulation',
    'Senior App Reviewers',
    'Support Staff',
)


def run():
    for group in GROUPS_TO_REMOVE:
        try:
            Group.objects.get(name=group).delete()
        except Group.DoesNotExist:
            pass
