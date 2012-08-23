from collections import defaultdict

from django.conf import settings

import jingo

from amo.decorators import no_login_required
from devhub.models import ActivityLog
from users.models import UserProfile


@no_login_required
def credits(request):

    developers = (UserProfile.objects
        .exclude(display_name=None)
        .filter(groupuser__group__name='Developers Credits')
        .order_by('display_name')
        .distinct())
    past_developers = (UserProfile.objects
        .exclude(display_name=None)
        .filter(groupuser__group__name='Past Developers Credits')
        .order_by('display_name')
        .distinct())
    other_contribs = (UserProfile.objects
        .exclude(display_name=None)
        .filter(groupuser__group__name='Other Contributors Credits')
        .order_by('display_name')
        .distinct())

    languages = sorted(list(
        set(settings.AMO_LANGUAGES + settings.HIDDEN_LANGUAGES) -
        set(['en-US'])))

    localizers = []
    for lang in languages:
        users = (UserProfile.objects
            .exclude(display_name=None)
            .filter(groupuser__group__name='%s Localizers' % lang)
            .order_by('display_name')
            .distinct())
        if users:
            localizers.append((lang, users))

    total_reviews = (ActivityLog.objects.total_reviews()
                                        .filter(approval_count__gt=10))
    reviewers = defaultdict(list)
    for total in total_reviews:
        cnt = total.get('approval_count', 0)
        if cnt > 1000:
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

    return jingo.render(request, 'pages/credits.html', context)
