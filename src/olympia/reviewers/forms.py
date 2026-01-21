import html
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta

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

import markupsafe
import waffle

import olympia.core.logger
from olympia import amo, ratings
from olympia.abuse.models import CinderJob, CinderPolicy, ContentDecision
from olympia.access import acl
from olympia.addons.models import Addon
from olympia.amo.forms import AMOModelForm
from olympia.amo.templatetags.jinja_helpers import format_datetime
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.reviewers import (
    HELD_DECISION_CHOICES,
    REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT,
)
from olympia.files.utils import SafeZip
from olympia.ratings.models import Rating
from olympia.ratings.permissions import user_can_delete_rating
from olympia.reviewers.models import (
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


class VersionsChoiceWidget(forms.SelectMultiple):
    """
    Widget to use together with WidgetRenderedModelMultipleChoiceField to display the
    list of versions used by review page for some actions.
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
            # Add our special `data-toggle` class and the right `data-value`
            # depending on what state the version is in.
            actions = self.actions_filters[obj.channel].get(status, []).copy()
            if status == amo.STATUS_DISABLED and obj.is_blocked:
                # We don't want blocked versions to get unrejected. Reply is
                # fine though.
                actions.remove('unreject_multiple_versions')
            if obj.pending_rejection:
                actions.append('change_or_clear_pending_rejection_multiple_versions')
            if needs_human_review:
                actions.append('clear_needs_human_review_multiple_versions')
            # Setting needs human review is available if the version is not
            # disabled or was signed. Note that we can record multiple reasons
            # for a version to require human review.
            if obj.file.status != amo.STATUS_DISABLED or obj.file.is_signed:
                actions.append('set_needs_human_review_multiple_versions')

            # If a version was auto-approved but deleted, we still want to
            # allow confirmation of its auto-approval.
            if obj.deleted and obj.was_auto_approved:
                actions.append('confirm_multiple_versions')

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
            obj.cinder_policy.full_text(text=obj.canned_response)
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
        is_appeal = obj.is_appeal
        queue_moves = list(obj.queue_moves.order_by('-created'))
        requeued_decisions = list(
            obj.decisions.filter(action=DECISION_ACTIONS.AMO_REQUEUE).order_by(
                '-created'
            )
        )
        forwarded = queue_moves[0].created if queue_moves else None
        requeued = requeued_decisions[0].created if requeued_decisions else None
        reports = obj.all_abuse_reports
        reasons_set = {(report.REASONS(report.reason).label,) for report in reports}
        messages_gen = (
            (
                (f'v[{report.addon_version}]: ' if report.addon_version else ''),
                report.message or '<no message>',
            )
            for report in reports
        )
        forwarded_or_requeued_notes = (
            [
                *(move.notes for move in queue_moves),
                *(decision.private_notes for decision in requeued_decisions),
            ]
            if requeued or forwarded
            else []
        )
        internal_notes = (
            ((f'Reasoning: {"; ".join(forwarded_or_requeued_notes)}',),)
            if forwarded_or_requeued_notes
            else ()
        )
        appeals = (
            (
                (appeal_obj.text, appeal_obj.reporter_report_id is not None)
                for appealed_decision in obj.appealed_decisions.all()
                for appeal_obj in appealed_decision.appeals.all()
            )
            if is_appeal
            else ()
        )
        is_developer_appeal = is_appeal and obj.is_developer_appeal
        subtexts_gen = [
            *internal_notes,
            *(
                (f'{"Reporter" if is_reporter else "Developer"} Appeal: {text}',)
                for text, is_reporter in appeals
            ),
        ]

        label = format_html(
            '(Created on {}) {}{}{}{}<br/><span>{}</span>'
            '<details><summary>Show detail on {} reports</summary><ul>{}</ul>'
            '</details>',
            format_datetime(obj.created),
            '[Appeal] ' if is_appeal else '',
            format_html('[Forwarded on {}] ', format_datetime(forwarded))
            if forwarded
            else '',
            format_html('[Requeued on {}] ', format_datetime(requeued))
            if requeued
            else '',
            format_html_join(', ', '"{}"', reasons_set),
            format_html_join('', '{}<br/>', subtexts_gen),
            len(reports),
            format_html_join('', '<li>{}{}</li>', messages_gen),
        )

        attrs = attrs or {}
        # Reviewers shouldn't use resolve_appeal_job to resolve "regular" jobs,
        # and conversely shouldn't use resolve_reports_job to resolve appeals,
        # as resolving appeals is a bit more involved.
        # On top of that, they shouldn't resolve *developer* appeals when
        # rejecting versions: that would cause the rejection to be no-op and
        # that's not always what we want.
        # The parent element will have `data-toggle-hide`, so data-value is
        # used to hide actions that are not supposed to be used for this job.
        hide_for_these_actions = [
            'resolve_appeal_job' if not is_appeal else 'resolve_reports_job'
        ]
        if is_developer_appeal:
            hide_for_these_actions.extend(('reject', 'reject_multiple_versions'))
        attrs['data-value'] = ' '.join(hide_for_these_actions)
        return super().create_option(
            name, value, label, selected, index, subindex, attrs
        )


class CinderPolicyWidget(forms.CheckboxSelectMultiple):
    """
    Widget to use together with a WidgetRenderedModelMultipleChoiceField to display
    select elements with additional attribute to allow toggling.
    """

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        obj = label
        label = str(obj)
        attrs = attrs or {}
        actions_on_policy = {
            DECISION_ACTIONS.from_api_value(action).value
            for action in obj.enforcement_actions
            if action in DECISION_ACTIONS.api_values
        }
        actions = (
            reviewer_action
            for reviewer_action, defn in self.helper_actions.items()
            # show this policy for this action if there any common enforcement actions
            if (ha_ea := defn.get('enforcement_actions', ()))
            and actions_on_policy.intersection(ha_ea)
        )
        attrs['class'] = 'data-toggle'
        attrs['data-value'] = ' '.join(actions)
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
                'Unsupported file type, please upload a file '
                f'{valid_extensions_string}.'
            )
        if value.size >= settings.MAX_UPLOAD_SIZE:
            raise forms.ValidationError('File too large.')
        try:
            if value.name.endswith('.zip'):
                # See clean_source() in WithSourceMixin
                zip_file = SafeZip(value)
                if zip_file.zip_file.testzip() is not None:
                    raise zipfile.BadZipFile()
        except (zipfile.BadZipFile, OSError, EOFError) as err:
            raise forms.ValidationError('Invalid or broken archive.') from err
    return value


class DelayedRejectionWidget(forms.RadioSelect):
    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        if not value:
            option['attrs']['class'] = 'data-toggle'
            if value is False:
                option['attrs']['data-value'] = 'reject_multiple_versions'
            else:  # Empty value is reserved for clearing pending rejection.
                option['attrs']['data-value'] = (
                    'change_or_clear_pending_rejection_multiple_versions'
                )
        return option


class DelayedRejectionDateWidget(forms.DateTimeInput):
    input_type = 'datetime-local'

    # Force the format to prevent seconds from showing up.
    def __init__(self, attrs=None, format='%Y-%m-%dT%H:%M'):
        super().__init__(attrs, format)


class PolicyValueMultiWidget(forms.MultiWidget):
    template_name = 'reviewers/widgets/policyvaluemultiwidget.html'

    def decompress(self, value):
        if not value:
            return [None for _ in self.widgets]
        return [pl_val for pl_vals in value.values() for pl_val in pl_vals]

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        # the subwidgets are in a consistent order - reverse so we can pop them off
        rvsubwidgets = list(reversed(context.get('widget', {}).get('subwidgets', [])))
        # swap out the placeholder for the subwidget context for the render
        context['policies'] = [
            (policy, [(txt, rvsubwidgets.pop() if key else None) for txt, key in pairs])
            for policy, pairs in self.policies
        ]
        return context


class PolicyValueMultiValueField(forms.MultiValueField):
    def __init__(self, queryset, **kw):
        self.queryset = queryset
        super().__init__(self.fields, **kw)

    def _get_queryset(self):
        return self._queryset

    def _set_queryset(self, queryset):
        self._queryset = None if queryset is None else queryset.all()
        self.fields = []
        self.widget.widgets_names = []
        self.widget.widgets = []

        # get the policy text split into text, placeholder pairs
        self.widget.policies = [
            (policy, policy.get_text_formatter_pairs())
            for policy in self._queryset or []
        ]
        # then add a field and widget for each placeholder
        for policy, pairs in self.widget.policies:
            for _, placeholder in pairs:
                if not placeholder:
                    continue
                field = forms.CharField(required=self.required)
                # set some properties on the instances to use in compress
                field.placeholder = placeholder
                field.policy = policy
                self.fields.append(field)
                self.widget.widgets_names.append(f'_{policy.id}_{placeholder}')
                self.widget.widgets.append(
                    forms.TextInput(attrs={'placeholder': placeholder})
                )

    queryset = property(_get_queryset, _set_queryset)

    def compress(self, data_list):
        data_list = data_list or [None for _ in self.fields]
        policy_values = defaultdict(dict)
        for field, value in zip(self.fields, data_list, strict=True):
            policy_values[field.policy.uuid][field.placeholder] = (
                html.unescape(value) if value else value
            )
        return policy_values


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
    versions = WidgetRenderedModelMultipleChoiceField(
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
    delayed_rejection = forms.NullBooleanField(
        initial=False,
        required=False,
        widget=DelayedRejectionWidget(
            choices=(
                (
                    True,
                    'Delay rejection, requiring developer to correct before…',
                ),
                (
                    False,
                    'Reject immediately.',
                ),
                (
                    None,
                    'Clear pending rejection.',
                ),
            )
        ),
    )
    delayed_rejection_date = forms.DateTimeField(
        widget=DelayedRejectionDateWidget,
        required=False,
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
    # queryset and widget are set later in __init__
    cinder_policies = WidgetRenderedModelMultipleChoiceField(
        # queryset is set later in __init__
        queryset=CinderPolicy.objects.none(),
        required=True,
        label='Choose one or more policies:',
        widget=CinderPolicyWidget(),
    )
    appeal_action = forms.MultipleChoiceField(
        required=False,
        label='Choose how to resolve appeal:',
        choices=(('deny', 'Deny Appeal(s)'),),
        widget=widgets.CheckboxSelectMultiple,
    )
    policy_values = PolicyValueMultiValueField(
        required=False,
        require_all_fields=False,
        widget=PolicyValueMultiWidget(widgets={}),
        # queryset is set later in __init__
        queryset=CinderPolicy.objects.none(),
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
            if not action.get('enforcement_actions'):
                self.fields['cinder_policies'].required = False
            else:
                # we no longer strictly require comments with cinder policies
                self.fields['comments'].required = False
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
        if self.cleaned_data.get('attachment_input') and self.cleaned_data.get(
            'attachment_file'
        ):
            self.add_error('attachment_input', 'Cannot upload both a file and input.')
        selected_action = self.cleaned_data.get('action')
        # If the user select a different type of job before changing actions there could
        # be non-appeal jobs selected as cinder_jobs_to_resolve under resolve_appeal_job
        # action, or appeal jobs under resolve_reports_job/a reject action. So filter
        # them out.
        if selected_action == 'resolve_appeal_job':
            self.cleaned_data['cinder_jobs_to_resolve'] = [
                job
                for job in self.cleaned_data.get('cinder_jobs_to_resolve', ())
                if job.is_appeal
            ]
        elif selected_action == 'resolve_reports_job':
            self.cleaned_data['cinder_jobs_to_resolve'] = [
                job
                for job in self.cleaned_data.get('cinder_jobs_to_resolve', ())
                if not job.is_appeal
            ]
        elif selected_action in ('reject', 'reject_multiple_versions'):
            self.cleaned_data['cinder_jobs_to_resolve'] = [
                job
                for job in self.cleaned_data.get('cinder_jobs_to_resolve', ())
                if not job.is_developer_appeal
            ]
        if self.cleaned_data.get('cinder_jobs_to_resolve') and self.cleaned_data.get(
            'cinder_policies'
        ):
            actions = CinderPolicy.get_decision_actions_from_policies(
                self.cleaned_data.get('cinder_policies'),
                for_entity=Addon,
            )
            if len(actions) == 0:
                self.add_error(
                    'cinder_policies',
                    'No policies selected with an associated cinder action.',
                )
            elif len(actions) > 1:
                self.add_error(
                    'cinder_policies',
                    'Multiple policies selected with different cinder actions.',
                )

        if self.helper.actions.get(selected_action, {}).get('delayable'):
            delayed_rejection = self.cleaned_data.get('delayed_rejection')
            delayed_rejection_date = self.cleaned_data.get('delayed_rejection_date')
            # Extra required checks are added here because the NullBooleanField
            # otherwise accepts missing data as `None`.
            if 'delayed_rejection' not in self.data:
                self.add_error(
                    'delayed_rejection',
                    self.fields['delayed_rejection'].error_messages['required'],
                )
            elif delayed_rejection and not self.data.get('delayed_rejection_date'):
                # In case reviewer selected delayed rejection option and
                # somehow cleared the date widget, raise an error.
                self.add_error(
                    'delayed_rejection_date',
                    self.fields['delayed_rejection'].error_messages['required'],
                )
            elif (
                selected_action == 'change_or_clear_pending_rejection_multiple_versions'
                and delayed_rejection
                and delayed_rejection_date
                and self.cleaned_data.get('versions')
            ):
                distinct_pending_rejection_dates = (
                    self.cleaned_data['versions']
                    .values_list('reviewerflags__pending_rejection')
                    .distinct()
                    .count()
                )
                if distinct_pending_rejection_dates > 1:
                    self.add_error(
                        'versions',
                        forms.ValidationError(
                            'Can only change the delayed rejection date of multiple '
                            'versions at once if their pending rejection dates are all '
                            'the same.'
                        ),
                    )

        if 'policy_values' in self.cleaned_data:
            # We only want to include placeholder values from selected policies
            selected_policy_uuids = [
                p.uuid for p in self.cleaned_data.get('cinder_policies', [])
            ]
            self.cleaned_data['policy_values'] = {
                uuid: (
                    vals if uuid in selected_policy_uuids else {k: None for k in vals}
                )
                for uuid, vals in self.cleaned_data['policy_values'].items()
            }

        return self.cleaned_data

    def clean_delayed_rejection_date(self):
        if self.cleaned_data.get('delayed_rejection_date'):
            if self.cleaned_data['delayed_rejection_date'] < self.min_rejection_date:
                raise ValidationError(
                    'Delayed rejection date should be at least one day in the future'
                )
        return self.cleaned_data.get('delayed_rejection_date')

    def clean_version_pk(self):
        version_pk = self.cleaned_data.get('version_pk')
        if version_pk and version_pk != self.helper.version.pk:
            raise ValidationError('Version mismatch - the latest version has changed!')

    def __init__(self, *args, **kw):
        self.helper = kw.pop('helper')
        super().__init__(*args, **kw)
        if waffle.switch_is_active('cinder_policy_review_reasons_enabled'):
            # When we're using policies reviewers shouldn't need to write as much
            self.fields['comments'].widget = forms.Textarea(attrs={'rows': 2})
        if any(action.get('delayable') for action in self.helper.actions.values()):
            # Default delayed rejection date should be
            # REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT days in the
            # future plus one hour to account for the time it's taking the
            # reviewer to actually perform the review.
            now = datetime.now()
            self.fields['delayed_rejection_date'].initial = now + timedelta(
                days=REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT, hours=1
            )
            # We enforce a reasonable min value on the widget.
            self.min_rejection_date = now + timedelta(days=1)
            delayed_rejection_date_widget_attrs = {
                'min': self.min_rejection_date.isoformat()[:16],
            }
            if not acl.action_allowed_for(
                self.helper.handler.user, amo.permissions.REVIEWS_ADMIN
            ):
                # Non-admin reviewers can't customize the date.
                delayed_rejection_date_widget_attrs['readonly'] = 'readonly'
            self.fields['delayed_rejection_date'].widget.attrs.update(
                delayed_rejection_date_widget_attrs
            )
        else:
            # No delayable action available, remove the fields entirely.
            del self.fields['delayed_rejection_date']
            del self.fields['delayed_rejection']

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
        ).select_related('parent')

        # Pass on the reviewer tools actions so we can set the show/hide on policies
        self.fields['cinder_policies'].widget.helper_actions = self.helper.actions

        self.fields['policy_values'].queryset = self.fields['cinder_policies'].queryset

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
        due_date_reasons = [entry.annotation for entry in NeedsHumanReview.REASONS]
        kw['initial'] = {'due_date_reasons': due_date_reasons}
        super().__init__(data, *args, **kw)
        self.fields['due_date_reasons'].choices = [
            (entry.annotation, entry.label) for entry in NeedsHumanReview.REASONS
        ]


class HeldDecisionReviewForm(forms.Form):
    cinder_job = WidgetRenderedModelMultipleChoiceField(
        label='Resolving Job:',
        required=False,
        queryset=CinderJob.objects.none(),
        widget=CinderJobsWidget(),
        disabled=True,
    )
    choice = forms.ChoiceField(widget=forms.RadioSelect)
    comments = forms.CharField(required=False)

    def __init__(self, *args, **kw):
        self.decision = kw.pop('decision')
        self.cinder_jobs_qs = CinderJob.objects.filter(decisions=self.decision)
        super().__init__(*args, **kw)

        if self.cinder_jobs_qs:
            # Set the queryset for cinder_job
            self.fields['cinder_job'].queryset = self.cinder_jobs_qs
            self.fields['cinder_job'].initial = [job.id for job in self.cinder_jobs_qs]
        if self.decision.addon:
            self.fields['choice'].choices = HELD_DECISION_CHOICES.ADDON.choices
        else:
            self.fields['choice'].choices = HELD_DECISION_CHOICES.OTHER.choices

    def clean(self):
        super().clean()
        if (
            not ContentDecision.objects.awaiting_action()
            .filter(id=self.decision.id)
            .exists()
        ):
            raise ValidationError('Not currently held for 2nd level approval')
