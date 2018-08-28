from django.contrib import admin
from django.contrib.admin.utils import flatten_fieldsets
from django.shortcuts import get_object_or_404
from django.utils.html import format_html
from django.utils.translation import ugettext, ugettext_lazy as _

from .models import AkismetReport
from .tasks import submit_to_akismet


class ReportedStatusFilter(admin.SimpleListFilter):
    title = _('Reported Status')
    parameter_name = 'reported_status'
    REPORTED_HAM = 'ham'
    REPORTED_SPAM = 'spam'
    UNREPORTED = 'unreported'
    QUERYSET_LOOKUP = {
        REPORTED_SPAM: {'reported': True,
                        'result__in': [AkismetReport.DEFINITE_SPAM,
                                       AkismetReport.MAYBE_SPAM]},
        REPORTED_HAM: {'reported': True,
                       'result': AkismetReport.HAM},
        UNREPORTED: {'reported': False},
    }
    VALUES = {
        REPORTED_SPAM: _('Reported Spam'),
        REPORTED_HAM: _('Reported Ham'),
        UNREPORTED: _('Not Reported'),
    }

    def lookups(self, request, model_admin):
        return self.VALUES.items()

    def queryset(self, request, queryset):
        filters = self.QUERYSET_LOOKUP.get(self.value(), {})
        return queryset.filter(**filters) if filters else queryset


@admin.register(AkismetReport)
class AkismetAdmin(admin.ModelAdmin):
    actions = ['submit_ham', 'submit_spam']
    fieldsets = (
        (None, {'fields': (
            'result', 'reported_status', 'rating',
        )}),
        (_('Content Submitted'), {'fields': (
            'comment_type', 'user_ip', 'user_agent', 'referrer', 'user_name',
            'user_email', 'user_homepage', 'comment', 'comment_modified',
            'content_link', 'content_modified',
        )}),
    )
    list_display = ('comment_type', 'comment', 'result', 'reported_status')
    list_filter = ('comment_type', 'result', ReportedStatusFilter,)
    readonly_fields = flatten_fieldsets(fieldsets)
    save_on_top = True
    search_fields = ('comment',)
    view_on_site = False

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        report = get_object_or_404(AkismetReport, pk=object_id)
        if report.reported:
            # We don't want the buttons if already submitted to Akismet.
            pass
        elif report.result == report.HAM:
            extra_context['action_value'] = 'submit_spam'
            extra_context['button_label'] = self.submit_spam.short_description
        elif report.result in [report.MAYBE_SPAM, report.DEFINITE_SPAM]:
            extra_context['action_value'] = 'submit_ham'
            extra_context['button_label'] = self.submit_ham.short_description
        return super(AkismetAdmin, self).change_view(
            request, object_id, form_url, extra_context=extra_context,
        )

    def reported_status(self, obj):
        labels = ReportedStatusFilter.VALUES
        if obj.reported:
            return (labels[ReportedStatusFilter.REPORTED_HAM] if obj.result
                    else labels[ReportedStatusFilter.REPORTED_SPAM])
        else:
            return labels[ReportedStatusFilter.UNREPORTED]

    def rating(self, obj):
        url = (
            obj.rating_instance.get_url_path() if obj.rating_instance
            else None)
        return format_html('<a href="{}">View Rating on site</a>', url)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def submit_ham(self, request, queryset):
        self.submit_report(request, queryset, False)
    submit_ham.short_description = _('Submit Ham to Akismet')

    def submit_spam(self, request, queryset):
        self.submit_report(request, queryset, True)
    submit_spam.short_description = _('Submit Spam to Akismet')

    def submit_report(self, request, qs, submit_spam):
        messages = []
        total_count = qs.count()
        if submit_spam:
            qs = qs.filter(reported=False, result=AkismetReport.HAM)
            report_ids = list(qs.values_list('id', flat=True))
            submit_to_akismet.delay(report_ids, True)
            messages.append(
                ugettext('%s Ham reports submitted as Spam') % len(report_ids))
        else:
            qs = qs.filter(reported=False, result__in=[
                AkismetReport.DEFINITE_SPAM, AkismetReport.MAYBE_SPAM])
            report_ids = list(qs.values_list('id', flat=True))
            submit_to_akismet.delay(report_ids, False)
            messages.append(
                ugettext('%s Spam reports submitted as Ham') % len(report_ids))

        total_count -= len(report_ids)
        if total_count:
            messages.append('%s reports ignored' % total_count)
        self.message_user(request, '; '.join(messages))
