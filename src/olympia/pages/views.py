from collections import defaultdict

from django.conf import settings
from django.db.transaction import non_atomic_requests

from olympia.activity.models import ActivityLog
from olympia.users.models import UserProfile
from olympia.amo.utils import render


@non_atomic_requests
def credits(request):

    developers = (UserProfile.objects
                  .exclude(display_name=None)
                  .filter(groupuser__group__name='Developers Credits')
                  .order_by('display_name')
                  .distinct())
    past_developers = (UserProfile.objects
                       .exclude(display_name=None)
                       .filter(
                           groupuser__group__name='Past Developers Credits')
                       .order_by('display_name')
                       .distinct())
    other_contribs = (UserProfile.objects
                      .exclude(display_name=None)
                      .filter(
                          groupuser__group__name='Other Contributors Credits')
                      .order_by('display_name')
                      .distinct())

    languages = sorted(list(set(settings.AMO_LANGUAGES) - set(['en-US'])))

    localizers = []
    for lang in languages:
        users = (UserProfile.objects
                 .exclude(display_name=None)
                 .filter(groupuser__group__name='%s Localizers' % lang)
                 .order_by('display_name')
                 .distinct())
        if users:
            localizers.append((lang, users))

    total_ratings = (ActivityLog.objects.total_ratings()
                                        .filter(approval_count__gt=10))
    reviewers = defaultdict(list)
    for total in total_ratings:
        cnt = total.get('approval_count', 0)
        if cnt > 10000:
            reviewers[10000].append(total)
        elif cnt > 5000:
            reviewers[5000].append(total)
        elif cnt > 2000:
            reviewers[2000].append(total)
        elif cnt > 1000:
            reviewers[1000].append(total)
        elif cnt > 500:
            reviewers[500].append(total)
        elif cnt > 100:
            reviewers[100].append(total)
        elif cnt > 10:
            reviewers[10].append(total)

    context = {
        'developers': developers,
        'past_developers': past_developers,
        'other_contribs': other_contribs,
        'localizers': localizers,
        'reviewers': reviewers,
    }

    return render(request, 'pages/credits.html', context)
