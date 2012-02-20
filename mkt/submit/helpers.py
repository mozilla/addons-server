from jingo import register, env
import jinja2

import mkt
from mkt.submit.models import AppSubmissionChecklist


@register.function
def progress(request, addon, step):
    if addon and addon.is_webapp():
        return NotImplementedError

    # TODO: We should probably not show the first step at all if user has
    # already read the developer agreement.
    completed = []
    checklist = AppSubmissionChecklist.objects.filter(addon=addon)
    if checklist.exists():
        completed = checklist[0].get_completed()
    elif step and step != 'terms':
        # We don't yet have a checklist yet if we just read the Dev Agreement.
        completed = ['terms']

    c = dict(steps=mkt.APP_STEPS, current=step, completed=completed)
    t = env.get_template('submit/helpers/progress.html').render(**c)
    return jinja2.Markup(t)
