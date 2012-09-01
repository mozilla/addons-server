from django.db import models


class Reindexing(models.Model):
    start_date = models.DateTimeField()
    old_index = models.CharField(max_length=255, null=True)
    new_index = models.CharField(max_length=255)
    alias = models.CharField(max_length=255)

    class Meta:
        db_table = 'zadmin_reindexing'
