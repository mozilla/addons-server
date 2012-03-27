import jinja2
from jingo import env

from amo.messages import debug, info, success, warning, error


def _make_message(message=None, title=None, title_safe=False,
                  message_safe=False):
    c = {'title': title, 'message': message,
         'title_safe': title_safe, 'message_safe': message_safe}
    t = env.get_template('site/messages/content.html').render(**c)
    return jinja2.Markup(t)
