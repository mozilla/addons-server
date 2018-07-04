from collections import defaultdict

from django import forms
from django.forms import widgets
from django.forms.utils import flatatt
from django.utils.translation import ugettext
from django.utils.html import format_html
from django.utils.safestring import mark_safe

import jinja2

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.files.models import File
from olympia.lib import happyforms
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.files')


class FileSelectWidget(widgets.Select):

    def render(self, name, value, attrs=None, renderer=None):
        context = self.get_context(name, value, attrs)

        rendered_attrs = flatatt(attrs)

        output = [format_html(
            '<select name="{}"{}>', name, rendered_attrs if attrs else ''
        )]
        output.extend(self.render_options(context))
        output.append(mark_safe('</select>'))
        return mark_safe(u''.join(output))

    def render_options(self, context):
        def option(files, label=None, deleted=False, channel=None):
            # Make sure that if there's a non-disabled version,
            # that's the one we use for the ID.
            files.sort(lambda a, b: ((a.status == amo.STATUS_DISABLED) -
                                     (b.status == amo.STATUS_DISABLED)))

            if label is None:
                label = u', '.join(f.get_platform_display() for f in files)

            output = [u'<option value="', jinja2.escape(files[0].id), u'" ']
            if selected in files:
                output.append(u' selected="true"')

            status = set(u'status-%s' % amo.STATUS_CHOICES_API[f.status]
                         for f in files)
            if deleted:
                status.update([u'status-deleted'])
            if channel:
                if channel == amo.RELEASE_CHANNEL_LISTED:
                    label += ' [AMO]'
                elif channel == amo.RELEASE_CHANNEL_UNLISTED:
                    label += ' [Self]'
            output.extend((u' class="', jinja2.escape(' '.join(status)), u'"'))
            output.extend((u'>', jinja2.escape(label), u'</option>\n'))
            return output

        selected_choices = []

        for group in context['widget']['optgroups']:
            select_option = group[1][0]
            if select_option['selected']:
                selected_choices.append(select_option['value'])

        if selected_choices and selected_choices[0]:
            selected = File.objects.get(id=selected_choices[0])
        else:
            selected = None

        file_ids = [int(c[0]) for c in self.choices if c[0]]

        output = []
        output.append(u'<option></option>')

        vers = Version.unfiltered.filter(files__id__in=file_ids).distinct()
        for ver in vers.order_by('-created'):
            hashes = defaultdict(list)
            for f in ver.files.filter(id__in=file_ids):
                hashes[f.hash].append(f)

            label = '{0} ({1})'.format(ver.version, ver.nomination)
            distinct_files = hashes.values()
            channel = ver.channel if self.should_show_channel else None
            if len(distinct_files) == 1:
                output.extend(
                    option(distinct_files[0], label, ver.deleted, channel))
            elif distinct_files:
                output.extend((u'<optgroup label="',
                               jinja2.escape(ver.version), u'">'))
                for f in distinct_files:
                    output.extend(
                        option(f, deleted=ver.deleted, channel=channel))
                output.append(u'</optgroup>')

        return output


class FileCompareForm(happyforms.Form):
    left = forms.ModelChoiceField(queryset=File.objects.all(),
                                  widget=FileSelectWidget)
    right = forms.ModelChoiceField(queryset=File.objects.all(),
                                   widget=FileSelectWidget, required=False)

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        self.request = kw.pop('request')
        super(FileCompareForm, self).__init__(*args, **kw)

        queryset = File.objects.filter(version__addon=self.addon)
        if acl.check_unlisted_addons_reviewer(self.request):
            should_show_channel = (
                queryset.filter(
                    version__channel=amo.RELEASE_CHANNEL_LISTED).exists() and
                queryset.filter(
                    version__channel=amo.RELEASE_CHANNEL_UNLISTED).exists())
        else:
            should_show_channel = False
            queryset = queryset.filter(
                version__channel=amo.RELEASE_CHANNEL_LISTED)

        self.fields['left'].queryset = queryset
        self.fields['right'].queryset = queryset
        self.fields['left'].widget.should_show_channel = should_show_channel
        self.fields['right'].widget.should_show_channel = should_show_channel

    def clean(self):
        if (not self.errors and
                self.cleaned_data.get('right') == self.cleaned_data['left']):
            raise forms.ValidationError(
                ugettext('Cannot diff a version against itself'))
        return self.cleaned_data
