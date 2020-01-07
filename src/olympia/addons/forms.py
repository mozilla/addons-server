from django.forms import ModelForm
from django.forms.models import BaseModelFormSet

import olympia.core.logger
from olympia import amo
from olympia.files.models import File
from olympia.versions.models import Version


admin_log = olympia.core.logger.getLogger('z.addons.admin')


class FileStatusForm(ModelForm):
    class Meta:
        model = File
        fields = ('status',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            if self.instance.version.deleted:
                self.fields['status'].disabled = True
                self.fields['status'].widget.attrs.update({'disabled': 'true'})
        except File.version.RelatedObjectDoesNotExist:
            pass


class AdminBaseFileFormSet(BaseModelFormSet):
    def __init__(self, instance=None, **kwargs):
        self.instance = instance

        if kwargs.pop('save_as_new', False):
            raise NotImplementedError
        super().__init__(**kwargs)

    @classmethod
    def get_default_prefix(cls):
        return 'files'

    def get_queryset(self):
        if not hasattr(self, '_queryset'):
            self.pager = amo.utils.paginate(
                self.request,
                Version.unfiltered.filter(addon=self.instance).values_list(
                    'pk', flat=True),
                30)
            # A list coercion so this doesn't result in a subquery with a LIMIT
            # which MySQL doesn't support (at this time).
            versions = list(self.pager.object_list)
            qs = super().get_queryset().filter(
                version__in=versions).order_by('-version__id')

            self._queryset = qs.select_related('version')
        return self._queryset

    def save_existing_objects(self, commit=True):
        objs = super().save_existing_objects(commit=commit)
        for form in self.initial_forms:
            if 'status' in form.changed_data:
                admin_log.info(
                    'Addon "%s" file (ID:%d) status changed to: %s' % (
                        self.instance.slug, form.instance.id,
                        form.cleaned_data['status']))
        return objs

    def save_new_objects(self, commit=True):
        # We don't support adding new File instances through this form
        self.new_objects = []
        return self.new_objects
