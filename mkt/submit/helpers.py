from jingo import register, env
import jinja2

import mkt
from mkt.submit.models import AppSubmissionChecklist


@register.function
def progress(addon, current):
    if not addon.is_webapp():
        return NotImplementedError
    completed = AppSubmissionChecklist.objects.get(addon=addon).get_completed()
    c = dict(steps=mkt.APP_STEPS, current=current, completed=completed)
    t = env.get_template('submit/helpers/progress.html').render(**c)
    return jinja2.Markup(t)
