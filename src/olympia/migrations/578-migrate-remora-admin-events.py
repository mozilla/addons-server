from datetime import datetime
from itertools import chain

from olympia import amo
from access.models import Group
from devhub.models import ActivityLog
from editors.models import EventLog
from users.models import UserProfile

# Are there other group changes we care about here?
# All of the old group IDs aside from Admins seem to have been deleted.
group_map = {
    1: 'Admins',
    2: 'Add-on Reviewers'
}


def run():
    new_groups = Group.objects.filter(name__in=group_map.values())
    new_groups = dict((g.name, g) for g in new_groups)

    for id, name in group_map.items():
        group_map[id] = new_groups[name]

    items = (EventLog.objects.values_list('action', 'user', 'added', 'removed',
                                          'changed_id', 'created')
                             .filter(type='admin',
                                     action__in=('group_addmember',
                                                 'group_removemember'),
                                     changed_id__in=group_map.keys())
                             .order_by('created'))

    user_ids = set(chain(*[(i[1], int(i[2] or i[3]))
                           for i in items
                           if (i[2] or i[3] or '').isdigit()]))

    users = dict((u.id, u)
                 for u in UserProfile.objects.filter(id__in=user_ids))

    for action, admin, added, removed, group_id, created in items:
        if action == 'group_addmember':
            user_id, action = added, amo.LOG.GROUP_USER_ADDED
        else:
            user_id, action = removed, amo.LOG.GROUP_USER_REMOVED

        if not user_id.isdigit():
            continue
        user_id = int(user_id)

        kw = {'created': created}
        if admin in users:
            kw['user'] = users[admin]

        if user_id in users:
            amo.log(action, group_map[group_id], users[user_id], **kw)

    # Fudge logs for editors who were added while logging was broken.
    created = datetime(2013, 3, 14, 3, 14, 15, 926535)
    user = group_map[1].users.all()[0]
    group = group_map[2]

    logs = (ActivityLog.objects.for_group(group)
                       .filter(action=amo.LOG.GROUP_USER_ADDED.id))

    editors = (UserProfile.objects.filter(groups=group)
                          .exclude(id__in=[l.arguments[1].id for l in logs]))
    for editor in editors:
        amo.log(amo.LOG.GROUP_USER_ADDED, group, editor, user=user,
                created=created)
