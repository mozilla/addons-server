from collections import defaultdict

from django import forms
from django.forms import widgets

import commonware.log
import happyforms
import jinja2
from tower import ugettext as _

import amo
from amo.urlresolvers import reverse
from files.models import File
from versions.models import Version

log = commonware.log.getLogger('z.files')


class FileSelectWidget(widgets.Select):
    def render_options(self, choices, selected_choices):
        def option(files, label=None):
            # Make sure that if there's a non-disabled version,
            # that's the one we use for the ID.
            files.sort(lambda a, b: ((a.status == amo.STATUS_DISABLED) -
                                     (b.status == amo.STATUS_DISABLED)))

            if label is None:
                label = ', '.join(str(os.platform) for os in f)

            output = ['<option value="', jinja2.escape(files[0].id), '" ']
            if files[0].status == amo.STATUS_DISABLED:
                # File viewer can't currently deal with disabled files
                output.append(' disabled="true"')
            if selected in files:
                output.append(' selected="true"')

            status = set('status-%s' % amo.STATUS_CHOICES_API[f.status]
                         for f in files)
            output.extend((' class="', jinja2.escape(' '.join(status)), '"'))

            output.extend(('>', jinja2.escape(label), '</option>\n'))
            return output

        if selected_choices[0]:
            selected = File.objects.get(id=selected_choices[0])
        else:
            selected = None

        file_ids = [int(c[0]) for c in self.choices if c[0]]

        output = []
        output.append('<option></option>')

        vers = Version.objects.filter(files__id__in=file_ids).distinct()
        for ver in vers.order_by('-created'):
            hashes = defaultdict(list)
            for f in (ver.files.select_related('platform')
                         .filter(id__in=file_ids)):
                hashes[f.hash].append(f)

            distinct_files = hashes.values()
            if len(distinct_files) == 1:
                output.extend(option(distinct_files[0], ver.version))
            elif distinct_files:
                output.extend(('<optgroup label="',
                               jinja2.escape(ver.version), '">'))
                for f in distinct_files:
                    output.extend(option(f))
                output.append('</optgroup>')

        return jinja2.Markup(''.join(output))


class FileCompareForm(happyforms.Form):
    left = forms.ModelChoiceField(queryset=File.objects.all(),
                                  widget=FileSelectWidget)
    right = forms.ModelChoiceField(queryset=File.objects.all(),
                                   widget=FileSelectWidget, required=False)

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        super(FileCompareForm, self).__init__(*args, **kw)

        queryset = (File.objects.filter(version__addon=self.addon)
                        .exclude(status=amo.STATUS_BETA))
        self.fields['left'].queryset = queryset
        self.fields['right'].queryset = queryset

    def clean(self):
        if (not self.errors and
            self.cleaned_data.get('right') == self.cleaned_data['left']):
            raise forms.ValidationError(
                _('Cannot diff a version against itself'))
        return self.cleaned_data
