from django import forms
from django.conf import settings
from django.utils.safestring import mark_safe


class IconWidgetRenderer(forms.RadioSelect.renderer):
    """ Return radiobox as a list of images. """

    def render(self):
        """ This will output radios as li>img+input. """
        output = []
        for w in self:
            value = w.choice_value
            if value.split('/')[0] == 'icon' or value == '':
                o = (("<li><a href='#' class='%s'><img src='%s/%s-32.png'>"
                      "</a>%s</li>") %
                     ('active' if self.value == w.choice_value else '',
                      settings.ADDON_ICONS_DEFAULT_URL, w.choice_label, w))
            else:
                o = "<li class='hide'>%s</li>" % w
            output.append(o)
        return mark_safe(u'\n'.join(output))

