from django import forms
from django.conf import settings
from django.utils.encoding import force_unicode
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe
from tower import ugettext as _

import users.notifications as email


class NotificationsSelectMultiple(forms.CheckboxSelectMultiple):
    """Widget that formats the notification checkboxes."""

    def __init__(self, **kwargs):
        super(self.__class__, self).__init__(**kwargs)

    def render(self, name, value, attrs=None):
        str_values = set([int(v) for v in value]) or []
        final_attrs = self.build_attrs(attrs, name=name)
        groups = {}

        for c in sorted(self.choices):
            notification = email.NOTIFICATIONS_BY_ID[c[0]]
            cb_attrs = dict(final_attrs, id='%s_%s' % (attrs['id'], c[0]))
            notes = []

            if notification.mandatory:
                cb_attrs = dict(cb_attrs, disabled=1)
                notes.append(u'<abbr title="required" class="req">*</abbr>')

            if c[1].new:
                notes.append(u'<sup class="msg">%s</sup>' % _('new'))

            cb = forms.CheckboxInput(
                cb_attrs, check_test=lambda value: value in str_values)

            rendered_cb = cb.render(name, c[0])
            label_for = u' for="%s"' % cb_attrs['id']

            groups.setdefault(notification.group, []).append(
                    u'<li><label class="check" %s>%s %s %s</label></li>' % (
                    label_for, rendered_cb, c[1], ''.join(notes)
                ))

        output = []
        template = u'<li><label>%s</label><ul class="checkboxes">%s</ul></li>'
        for e, name in email.NOTIFICATION_GROUPS.items():
            if e in groups:
                output.append(template % (name, u'\n'.join(groups[e])))

        return mark_safe(u'<ol class="complex">%s</ul>' % u'\n'.join(output))

