from django.db import models


class Session(models.Model):
    """
    Deprecated.

    Note after we are no longer dependent on Remora/Cake this model, the
    associated table, and the entire app in which it resides will be obsolete.
    """

    class Meta:
        db_table = 'cake_sessions'

    session_id = models.CharField(db_column="id", unique=True,
        primary_key=True, max_length=32)
    data = models.TextField()
    expires = models.IntegerField()
