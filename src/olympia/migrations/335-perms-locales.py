from django.conf import settings

from access.models import Group, GroupUser


LANGS = sorted(list(
    set(settings.AMO_LANGUAGES + settings.HIDDEN_LANGUAGES) -
    set(['en-US'])))


def run():
    Group.objects.create(pk=50006, name='Senior Localizers',
                         rules='Locales:Edit')

    for idx, locale in enumerate(LANGS):
        pk = 50007 + idx
        name = '%s Localizers' % locale
        rules = 'Locale.%s:Edit,L10nTools:View' % locale
        group = Group.objects.create(pk=pk, name=name, rules=rules)
        print('New group created: (%d) %s' % (pk, name))

        try:
            old_group = Group.objects.get(pk__lt=50000, name=name)
        except Group.DoesNotExist:
            print('Old group not found: %s' % name)
            continue

        # Rename old groups so they are distinguisable.
        old_group.update(name=old_group.name + ' (OLD)')

        # Migrate users to new group.
        cnt = 0
        for user in old_group.users.all():
            cnt += 1
            GroupUser.objects.create(group=group, user=user)
        print('Migrated %d users to new group (%s)' % (cnt, name))
