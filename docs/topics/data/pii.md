# PII

(pii)=

PII stands for Personally Identifiable Information. This section describes
the different types of PII data in AMO and how we handle it.

## Identifiying PII data

Define a model's pii fields using the `Meta.pii_fields` attribute:

```python
class MyModel(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField()
    age = models.IntegerField()

    class Meta:
        pii_fields = ['name', 'email']
```

The `pii_fields` attribute is a list of field names that are considered PII.
Identifying these fields can be useful when filtering data for sensitive exposure,
or when auditing our database, and are used during garbage collection via data retention policies.

We can introspeect the database to find all the fields that are pii:

> [!NOTE]
> This command will return all fields that are marked as pii in all models.

```bash
./manage.py pii
```

> [!IMPORTANT]
> PII fields must be nullable in order to support the anonymization of PII data.

## Types of PII data

Types of PII data we have in AMO include:

- IP addresses
- User profile data (name, Fxa account ID, etc.)
- Email addresses
- Phone numbers

## How we handle PII data

When an instance is soft deleted we typically anonymize the PII data.
We should improve this process to take advantage of database introspection.
