import zipfile
from datetime import timedelta

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef
from django.forms import widgets
from django.forms.models import (
    BaseModelFormSet,
    ModelMultipleChoiceField,
    modelformset_factory,
)
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext

import markupsafe

import olympia.core.logger
from olympia import amo, ratings
from olympia.abuse.models import CinderJob, CinderPolicy
from olympia.access import acl
from olympia.amo.forms import AMOModelForm
from olympia.constants.reviewers import REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT
from olympia.files.utils import SafeZip
from olympia.ratings.models import Rating
from olympia.ratings.permissions import user_can_delete_rating
from olympia.reviewers.models import (
    VIEW_QUEUE_FLAGS,
    NeedsHumanReview,
    ReviewActionReason,
    Whiteboard,
)
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.reviewers.forms')


ACTION_FILTERS = (
    ('', ''),
    ('approved', 'Approved reviews'),
    ('deleted', 'Deleted reviews'),
)

ACTION_DICT = dict(approved=amo.LOG.APPROVE_RATING, deleted=amo.LOG.DELETE_RATING)

VALID_ATTACHMENT_EXTENSIONS = ('.txt', '.zip')


class RatingModerationLogForm(forms.Form):
    start = forms.DateField(required=False, label='View entries between')
    end = forms.DateField(required=False, label='and')
    filter = forms.ChoiceField(
        required=False, choices=ACTION_FILTERS, label='Filter by type/action'
    )

    def clean(self):
        data = self.cleaned_data
        # We want this to be inclusive of the end date.
        if 'end' in data and data['end']:
            data['end'] += timedelta(days=1)

        if 'filter' in data and data['filter']:
            data['filter'] = ACTION_DICT[data['filter']]
        return data


class ReviewLogForm(forms.Form):
    start = forms.DateField(required=False, label='View entries between')
    end = forms.DateField(required=False, label='and')
    search = forms.CharField(required=False, label='containing')

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)

        self.fields['start'].widget.attrs = {
            'placeholder': 'start',
            'size': 10,
        }

        self.fields['end'].widget.attrs = {'size': 10, 'placeholder': 'end'}

        search_ph = 'add-on, reviewer or comment'
        self.fields['search'].widget.attrs = {'placeholder': search_ph, 'size': 30}

    def clean(self):
        data = self.cleaned_data
        # We want this to be inclusive of the end date.
        if 'end' in data and data['end']:
            data['end'] += timedelta(days=1)

        return data


class NonValidatingChoiceField(forms.ChoiceField):
    """A ChoiceField that doesn't validate."""

    def validate(self, value):
        pass


class NumberInput(widgets.Input):
    input_type = 'number'


class VersionsChoiceField(ModelMultipleChoiceField):
    """
    Widget to use together with VersionsChoiceWidget to display the list of
    versions used by review page for some actions.
    """

    def label_from_instance(self, obj):
        """Return the object instead of transforming into a label at this stage
        so that it's available in the widget."""
        return obj


class VersionsChoiceWidget(forms.SelectMultiple):
    """
    Widget to use together with VersionsChoiceField to display the list of
    versions used by review page for some actions.
    """

    actions_filters = {
        amo.CHANNEL_UNLISTED: {
            amo.STATUS_APPROVED: [
                'block_multiple_versions',
                'confirm_multiple_versions',
                'reject_multiple_versions',
                'reply',
            ],
            amo.STATUS_AWAITING_REVIEW: [
                'approve_multiple_versions',
                'reject_multiple_versions',
                'reply',
            ],
            amo.STATUS_DISABLED: [
                'unreject_multiple_versions',
                'reply',
            ],
        },
        amo.CHANNEL_LISTED: {
            amo.STATUS_APPROVED: [
                'block_multiple_versions',
                'reject_multiple_versions',
                'reply',
            ],
            amo.STATUS_AWAITING_REVIEW: [
                'approve_multiple_versions',
                'reject_multiple_versions',
                'reply',
            ],
            amo.STATUS_DISABLED: [
                'unreject_multiple_versions',
                'reply',
            ],
        },
    }

    def create_option(self, *args, **kwargs):
        option = super().create_option(*args, **kwargs)
        # label_from_instance() on VersionsChoiceField returns the full object,
        # not a label, this is what makes this work.
        obj = option['label']
        if getattr(self, 'versions_actions', None):
            status = obj.file.status if obj.file else None
            # We annotate that needs_human_review property in review().
            needs_human_review = getattr(obj, 'needs_human_review', False)
            if status == amo.STATUS_DISABLED and obj.is_blocked:
                # Override status for blocked versions: we don't want them
                # unrejected.
                status = None
            # Add our special `data-toggle` class and the right `data-value`
            # depending on what state the version is in.
            actions = self.actions_filters[obj.channel].get(status, []).copy()
            if obj.pending_rejection:
                actions.append('clear_pending_rejection_multiple_versions')
            if needs_human_review:
                actions.append('clear_needs_human_review_multiple_versions')
            # Setting needs human review is available if the version is not
            # disabled or was signed. Note that we can record multiple reasons
            # for a version to require human review.
            if obj.file.status != amo.STATUS_DISABLED or obj.file.is_signed:
                actions.append('set_needs_human_review_multiple_versions')
            option['attrs']['class'] = 'data-toggle'
            option['attrs']['data-value'] = ' '.join(actions)
        # Just in case, let's now force the label to be a string (it would be
        # converted anyway, but it's probably safer that way).
        option['label'] = (
            str(obj)
            + markupsafe.Markup(
                f' - {obj.get_review_status_display(True)}' if obj else ''
            )
            + (' (needs human review)' if needs_human_review else '')
        )
        return option


class WidgetRenderedModelMultipleChoiceField(ModelMultipleChoiceField):
    """
    Field to use together with a suitable Widget subclass to pass down the object to be
    rendered.
    """

    def label_from_instance(self, obj):
        """Return the object instead of transforming into a label at this stage
        so that it's available in the widget."""
        return obj


class ReasonsChoiceWidget(forms.CheckboxSelectMultiple):
    """
    Widget to use together with a WidgetRenderedModelMultipleChoiceField to display
    checkboxes with extra data for the canned responses.
    """

    def create_option(self, *args, **kwargs):
        option = super().create_option(*args, **kwargs)
        # label_from_instance() on WidgetRenderedModelMultipleChoiceField returns the
        # full object, not a label, this is what makes this work.
        obj = option['label']
        canned_response = (
            obj.cinder_policy.full_text(obj.canned_response)
            if obj.cinder_policy
            else obj.canned_response
        )
        option['attrs']['data-value'] = f'- {canned_response}\n'
        option['label'] = str(obj)
        return option


class CinderJobsWidget(forms.CheckboxSelectMultiple):
    """
    Widget to use together with a WidgetRenderedModelMultipleChoiceField to display
    select elements with additional attribute to allow toggling.
    """

    option_template_name = 'reviewers/includes/input_option_with_label_attrs.html'

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        # label_from_instance() on WidgetRenderedModelMultipleChoiceField returns the
        # full object, not a label, this is what makes this work.
        obj = label
        forwarded_notes = [
            *obj.forwarded_from_jobs.all().values_list('decision__notes', flat=True),
            *obj.queue_moves.values_list('notes', flat=True),
        ]
        is_appeal = obj.is_appeal
        reports = obj.all_abuse_reports
        reasons_set = {
            (report.REASONS.for_value(report.reason).display,) for report in reports
        }
        messages_gen = (
            (
                (f'v[{report.addon_version}]: ' if report.addon_version else ''),
                report.message or '<no message>',
            )
            for report in reports
        )
        forwarded = (
            ((f'Reasoning: {"; ".join(notes for notes in forwarded_notes)}',),)
            if forwarded_notes
            else ()
        )
        appeals = (
            (appeal_text_obj.text, appeal_text_obj.reporter_report is not None)
            for appealed_decision in obj.appealed_decisions.all()
            for appeal_text_obj in appealed_decision.appeals.all()
        )
        subtexts_gen = [
            *forwarded,
            *(
                (f'{"Reporter" if is_reporter else "Developer"} Appeal: {text}',)
                for text, is_reporter in appeals
            ),
        ]

        label = format_html(
            '{}{}{}<details><summary>Show detail on {} reports</summary>'
            '<span>{}</span><ul>{}</ul></details>',
            '[Appeal] ' if is_appeal else '',
            '[Forwarded] ' if forwarded else '',
            format_html_join(', ', '"{}"', reasons_set),
            len(reports),
            format_html_join('', '{}<br/>', subtexts_gen),
            format_html_join('', '<li>{}{}</li>', messages_gen),
        )

        attrs = attrs or {}
        attrs['data-value'] = (
            'resolve_appeal_job' if not is_appeal else 'resolve_reports_job'
        )
        return super().create_option(
            name, value, label, selected, index, subindex, attrs
        )


class ActionChoiceWidget(forms.RadioSelect):
    """
    Widget to add boilerplate_text to action options.
    """

    def create_option(self, *args, **kwargs):
        option = super().create_option(*args, **kwargs)
        actions = getattr(self, 'actions', {})
        action = actions.get(option['value'], None)
        if action:
            boilerplate_text = action.get('boilerplate_text', None)
            if boilerplate_text:
                option['attrs']['data-value'] = boilerplate_text

        return option


def validate_review_attachment(value):
    if value:
        if not value.name.endswith(VALID_ATTACHMENT_EXTENSIONS):
            valid_extensions_string = '(%s)' % ', '.join(VALID_ATTACHMENT_EXTENSIONS)
            raise forms.ValidationError(
                gettext(
                    'Unsupported file type, please upload a '
                    'file {extensions}.'.format(extensions=valid_extensions_string)
                )
            )
        if value.size >= settings.MAX_UPLOAD_SIZE:
            raise forms.ValidationError(gettext('File too large.'))
        try:
            if value.name.endswith('.zip'):
                # See clean_source() in WithSourceMixin
                zip_file = SafeZip(value)
                if zip_file.zip_file.testzip() is not None:
                    raise zipfile.BadZipFile()
        except (zipfile.BadZipFile, OSError, EOFError) as err:
            raise forms.ValidationError(gettext('Invalid or broken archive.')) from err
    return value


class ReviewForm(forms.Form):
    # Hack to restore behavior from pre Django 1.10 times.
    # Django 1.10 enabled `required` rendering for required widgets. That
    # wasn't the case before, this should be fixed properly but simplifies
    # the actual Django 1.11 deployment for now.
    # See https://github.com/mozilla/addons-server/issues/8912 for proper fix.
    use_required_attribute = False

    comments = forms.CharField(
        required=True, widget=forms.Textarea(), label='Comments:'
    )
    action = forms.ChoiceField(required=True, widget=ActionChoiceWidget)
    versions = VersionsChoiceField(
        # The <select> is displayed/hidden dynamically depending on the action
        # so it needs the data-toggle class (data-value attribute is set later
        # during __init__). VersionsChoiceWidget takes care of adding that to
        # the individual <option> which is also needed for unlisted review
        # where for some actions we display the dropdown hiding some of the
        # versions it contains.
        widget=VersionsChoiceWidget(attrs={'class': 'data-toggle'}),
        required=False,
        queryset=Version.objects.none(),
    )  # queryset is set later in __init__.

    operating_systems = forms.CharField(required=False, label='Operating systems:')
    applications = forms.CharField(required=False, label='Applications:')
    delayed_rejection = forms.BooleanField(
        # For the moment we default to immediate rejections, but in the future
        # this will have to be dynamically set in __init__() to default to
        # delayed for listed review, and immediate for unlisted (the default
        # matters especially for unlisted where we don't intend to even show
        # the inputs, so we'll always use the initial value).
        # See https://github.com/mozilla/addons-server/pull/15025
        initial=False,
        required=False,
        widget=forms.RadioSelect(
            choices=(
                (
                    True,
                    'Delay rejection, requiring developer to correct in ' 'less than…',
                ),
                (
                    False,
                    'Reject immediately. Only use in case of serious '
                    'security issues.',
                ),
            )
        ),
    )
    delayed_rejection_days = forms.IntegerField(
        required=False,
        widget=NumberInput,
        initial=REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT,
        label='days',
        min_value=1,
        max_value=99,
    )
    reasons = WidgetRenderedModelMultipleChoiceField(
        label='Choose one or more reasons:',
        # queryset is set later in __init__.
        queryset=ReviewActionReason.objects.none(),
        required=True,
        widget=ReasonsChoiceWidget,
    )
    attachment_file = forms.FileField(
        required=False,
        validators=[validate_review_attachment],
        widget=forms.ClearableFileInput(
            attrs={'data-max-upload-size': settings.MAX_UPLOAD_SIZE}
        ),
    )
    attachment_input = forms.CharField(required=False, widget=forms.Textarea())

    version_pk = forms.IntegerField(required=False, min_value=1)
    cinder_jobs_to_resolve = WidgetRenderedModelMultipleChoiceField(
        label='Outstanding DSA related reports to resolve:',
        required=False,
        queryset=CinderJob.objects.none(),
        widget=CinderJobsWidget(attrs={'class': 'data-toggle-hide'}),
    )

    cinder_policies = forms.ModelMultipleChoiceField(
        # queryset is set later in __init__
        queryset=CinderPolicy.objects.none(),
        required=True,
        label='Choose one or more policies:',
        widget=widgets.CheckboxSelectMultiple,
    )
    appeal_action = forms.MultipleChoiceField(
        required=False,
        label='Choose how to resolve appeal:',
        choices=(('deny', 'Deny Appeal(s)'),),
        widget=widgets.CheckboxSelectMultiple,
    )

    def is_valid(self):
        # Some actions do not require comments and reasons.
        selected_action = self.data.get('action')
        action = self.helper.actions.get(selected_action)
        if action:
            if not action.get('comments', True):
                self.fields['comments'].required = False
            if action.get('multiple_versions', False):
                self.fields['versions'].required = True
            if not action.get('requires_reasons', False):
                self.fields['reasons'].required = False
            if not action.get('requires_policies'):
                self.fields['cinder_policies'].required = False
            if self.data.get('cinder_jobs_to_resolve'):
                # if a cinder job is being resolved we need a review reason
                if action.get('requires_reasons_for_cinder_jobs'):
                    self.fields['reasons'].required = True
            if selected_action == 'resolve_appeal_job':
                self.fields['appeal_action'].required = True
        result = super().is_valid()
        if result:
            self.helper.set_data(self.cleaned_data)
        return result

    def clean(self):
        super().clean()
        # If the user select a different type of job before changing actions there could
        # be non-appeal jobs selected as cinder_jobs_to_resolve under resolve_appeal_job
        # action, or appeal jobs under resolve_reports_job action. So filter them out.
        if self.cleaned_data.get('attachment_input') and self.cleaned_data.get(
            'attachment_file'
        ):
            raise ValidationError('Cannot upload both a file and input.')
        if self.cleaned_data.get('action') == 'resolve_appeal_job':
            self.cleaned_data['cinder_jobs_to_resolve'] = [
                job
                for job in self.cleaned_data.get('cinder_jobs_to_resolve', ())
                if job.is_appeal
            ]
        elif self.cleaned_data.get('action') == 'resolve_reports_job':
            self.cleaned_data['cinder_jobs_to_resolve'] = [
                job
                for job in self.cleaned_data.get('cinder_jobs_to_resolve', ())
                if not job.is_appeal
            ]
        if self.cleaned_data.get('cinder_jobs_to_resolve') and self.cleaned_data.get(
            'cinder_policies'
        ):
            actions = self.helper.handler.get_cinder_actions_from_policies(
                self.cleaned_data.get('cinder_policies')
            )
            if len(actions) == 0:
                raise ValidationError(
                    'No policies selected with an associated cinder action.'
                )
            elif len(actions) > 1:
                raise ValidationError(
                    'Multiple policies selected with different cinder actions.'
                )
        return self.cleaned_data

    def clean_version_pk(self):
        version_pk = self.cleaned_data.get('version_pk')
        if version_pk and version_pk != self.helper.version.pk:
            raise ValidationError('Version mismatch - the latest version has changed!')

    def __init__(self, *args, **kw):
        self.helper = kw.pop('helper')
        super().__init__(*args, **kw)

        # Delayed rejection period needs to be readonly unless we're an admin.
        user = self.helper.handler.user
        rejection_period_widget_attributes = {}
        rejection_period = self.fields['delayed_rejection_days']
        if not acl.action_allowed_for(user, amo.permissions.REVIEWS_ADMIN):
            rejection_period.min_value = rejection_period.initial
            rejection_period.max_value = rejection_period.initial
            rejection_period_widget_attributes['readonly'] = 'readonly'
        rejection_period_widget_attributes['min'] = rejection_period.min_value
        rejection_period_widget_attributes['max'] = rejection_period.max_value
        rejection_period.widget.attrs.update(rejection_period_widget_attributes)

        # With the helper, we now have the add-on and can set queryset on the
        # versions field correctly. Small optimization: we only need to do this
        # if the relevant actions are available, otherwise we don't really care
        # about this field.
        versions_actions = [
            k
            for k in self.helper.actions
            if self.helper.actions[k].get('multiple_versions')
        ]
        if versions_actions:
            if self.helper.version:
                channel = self.helper.version.channel
            else:
                channel = amo.CHANNEL_LISTED
            needs_human_review_qs = NeedsHumanReview.objects.filter(
                is_active=True, version=OuterRef('pk')
            )
            self.fields['versions'].widget.versions_actions = versions_actions
            self.fields['versions'].queryset = (
                self.helper.addon.versions(manager='unfiltered_for_relations')
                .filter(channel=channel)
                .no_transforms()
                .select_related('file')
                .select_related('autoapprovalsummary')
                .select_related('reviewerflags')
                .annotate(needs_human_review=Exists(needs_human_review_qs))
                .order_by('created')
            )
            # Reset data-value depending on widget depending on actions available.
            self.fields['versions'].widget.attrs['data-value'] = ' '.join(
                versions_actions
            )

        # Set choices on the action field dynamically to raise an error when
        # someone tries to use an action they don't have access to.
        self.fields['action'].choices = [
            (k, v['label']) for k, v in self.helper.actions.items()
        ]

        # Set the queryset for reasons based on the add-on type.
        self.fields['reasons'].queryset = ReviewActionReason.objects.filter(
            is_active=True,
            addon_type__in=[
                amo.ADDON_ANY,
                amo.ADDON_STATICTHEME
                if self.helper.addon.type == amo.ADDON_STATICTHEME
                else amo.ADDON_EXTENSION,
            ],
        ).exclude(canned_response='')

        # Add actions from the helper into the action widget so we can access
        # them in create_option.
        self.fields['action'].widget.actions = self.helper.actions

        # Set the queryset for cinderjobs to resolve
        self.fields[
            'cinder_jobs_to_resolve'
        ].queryset = self.helper.unresolved_cinderjob_qs

        # Set the queryset for policies to show as options
        self.fields['cinder_policies'].queryset = CinderPolicy.objects.filter(
            expose_in_reviewer_tools=True
        )

    @property
    def unreviewed_files(self):
        return (
            (self.helper.version.file,)
            if self.helper.version
            and self.helper.version.file.status == amo.STATUS_AWAITING_REVIEW
            else ()
        )


class MOTDForm(forms.Form):
    motd = forms.CharField(required=True, widget=widgets.Textarea())


class WhiteboardForm(AMOModelForm):
    class Meta:
        model = Whiteboard
        fields = ['private', 'public']
        labels = {'private': 'Private Whiteboard', 'public': 'Whiteboard'}


class PublicWhiteboardForm(AMOModelForm):
    class Meta:
        model = Whiteboard
        fields = ['public']
        labels = {'public': 'Whiteboard'}


class ModerateRatingFlagForm(AMOModelForm):
    action_choices = [
        (ratings.REVIEW_MODERATE_KEEP, 'Keep review; remove flags'),
        (ratings.REVIEW_MODERATE_SKIP, 'Skip for now'),
        (ratings.REVIEW_MODERATE_DELETE, 'Delete review'),
    ]
    action = forms.ChoiceField(
        choices=action_choices, required=False, initial=0, widget=forms.RadioSelect()
    )

    class Meta:
        model = Rating
        fields = ('action',)


class BaseRatingFlagFormSet(BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

    def save(self):
        for form in self.forms:
            if form.cleaned_data and user_can_delete_rating(
                self.request, form.instance
            ):
                action = int(form.cleaned_data['action'])

                if action == ratings.REVIEW_MODERATE_DELETE:
                    form.instance.delete()
                elif action == ratings.REVIEW_MODERATE_KEEP:
                    form.instance.approve()


RatingFlagFormSet = modelformset_factory(
    Rating, extra=0, form=ModerateRatingFlagForm, formset=BaseRatingFlagFormSet
)


class ReviewQueueFilter(forms.Form):
    due_date_reasons = forms.MultipleChoiceField(
        choices=(), widget=forms.CheckboxSelectMultiple, required=False
    )

    def __init__(self, data, *args, **kw):
        due_date_reasons = list(Version.objects.get_due_date_reason_q_objects().keys())
        kw['initial'] = {'due_date_reasons': due_date_reasons}
        super().__init__(data, *args, **kw)
        labels = {reason: label for reason, label in VIEW_QUEUE_FLAGS}
        self.fields['due_date_reasons'].choices = [
            (reason, labels.get(reason, reason)) for reason in due_date_reasons
        ]


class HeldDecisionReviewForm(forms.Form):
    cinder_job = WidgetRenderedModelMultipleChoiceField(
        label='Resolving Job:',
        required=False,
        queryset=CinderJob.objects.none(),
        widget=CinderJobsWidget(),
        disabled=True,
    )
    choice = forms.ChoiceField(
        choices=(('yes', 'Proceed with action'), ('no', 'Approve content instead')),
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, **kw):
        jobs_qs = kw.pop('cinder_jobs_qs')
        super().__init__(*args, **kw)

        if jobs_qs:
            # Set the queryset for cinder_job
            self.fields['cinder_job'].queryset = jobs_qs
            self.fields['cinder_job'].initial = [job.id for job in jobs_qs]
            if jobs_qs[0].target_addon:
                self.fields['choice'].choices += (
                    ('forward', 'Forward to Reviewer Tools'),
                )
