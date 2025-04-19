# PII

(pii)=

PII stands for Personally Identifiable Information. This section describes
the different types of PII data in AMO and how we handle it.

## Identifiying PII data

We have a custom property on all django model fields called `pii`. If this
property is set to `True`, the field is considered to contain PII and we take
extra care when interacting with it.

```python
class MyModel(models.Model):
    name = models.CharField(max_length=255, pii=True)
    email = models.EmailField(pii=True)
```

When setting a field to `pii=True`, we add a noop migration to indicate
that it is pii and when that happened.

We can introspeect the database to find all the fields that are pii:

> [!NOTE]
> This command will return all fields that are marked as pii in all models.

```bash
./manage.py pii
```

> [!IMPORTANT]
> We should increase the scope of this field property to guarantee that PII
> fields are nullable, enabling the anonymization of PII data.

## Types of PII data

Types of PII data we have in AMO include:

- IP addresses
- User profile data (name, Fxa account ID, etc.)
- Email addresses
- Phone numbers

## How we handle PII data

When an instance is soft deleted we typically anonymize the PII data.
We should improve this process to take advantage of database introspection.
