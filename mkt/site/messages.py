import jinja2
from jingo import env
from tower import ugettext as _

from amo.messages import debug, info, success, warning, error


def _make_message(message=None, title=None, title_safe=False,
                  message_safe=False):
    c = {'title': title, 'message': message,
         'title_safe': title_safe, 'message_safe': message_safe}
    t = env.get_template('site/messages/content.html').render(c)
    return jinja2.Markup(t)


def form_errors(request):
    return error(request, title=_('Errors Found'),
        message=_('There were errors in the changes you made. '
                  'Please correct them and resubmit.'))
