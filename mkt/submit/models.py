from django.db import models

import mkt


class AppSubmissionChecklist(models.Model):
    addon = models.OneToOneField('addons.Addon')
    terms = models.BooleanField()
    manifest = models.BooleanField()
    details = models.BooleanField()
    payments = models.BooleanField()

    class Meta:
        db_table = 'submission_checklist_apps'

    def get_completed(self):
        """Return a list of completed submission steps."""
        completed = []
        for step, label in mkt.APP_STEPS:
            if getattr(self, step, False):
                completed.append(step)
        return completed
