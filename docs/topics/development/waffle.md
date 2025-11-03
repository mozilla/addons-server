# Waffle

We use [waffle](https://waffle.readthedocs.io/en/stable/) for managing feature access in production.

## Why switches and not flags

We prefer to use [switches](https://waffle.readthedocs.io/en/stable/types/switch.html)
over flags in most cases as switches are:

- switches are simple
- switches are easy to reason about

Flags can be used if you want to do a gradual rollout a feature over time or to a subset of users.

## Creating/Deleting a switch

Switches are added via database migrations.
This ensures the switch exists in all environments once the migration is run.

To create or remove a switch,
first create an empty migration in the app where your switch will live.

```bash
python ./manage.py makemigrations <app> --empty
```

### Creating a switch

add the switch in the migration

```python
from django.db import migrations

from olympia.core.db.migrations import CreateWaffleSwitch

class Migration(migrations.Migration):

    dependencies = [
        ('app', '0001_auto_20220531_2434'),
    ]

    operations = [
        CreateWaffleSwitch('foo')
    ]
```

### Deleting a switch

remove the switch in the migration

```python

from django.db import migrations

from olympia.core.db.migrations import DeleteWaffleSwitch

class Migration(migrations.Migration):

    dependencies = [
        ('app', '0001_auto_20220531_2434'),
    ]

    operations = [
        DeleteWaffleSwitch('foo')
    ]
```

## Using a switch

Use your switch in python code

```python
if waffle.switch_is_active('foo'):
    # do something
```

Use your switch in jinja2

```django
{% if waffle.switch_is_active('foo') %}
    <p>foo is active</p>
{% endif %}
```

## Testing

Testing the result of a switch being on or off is important
to ensure your switch behaves appropriately. We can override the value of a switch easily.

Override for an entire test case

```python
# Override an entire test case class
@override_switch('foo', active=True)
class TestFoo(TestCase):
    def test_bar(self):
        assert waffle.switch_is_active('foo')

    # Override an individual test method
    @override_switch('foo', active=False)
    def test_baz(self):
        assert not waffle.switch_is_active('foo')
```

## Enabling your switch

Once your switch is deployed, you can enable it in a given environment by following these steps.

1. ssh into a kubernetes pod in the environment you want to enable the switch in. ([instructions][devops])
2. run the CLI command to enable your switch ([instructions][waffle-cli])

Toggling a switch on

```bash
./manage.py waffle_switch foo on
```

Once you've ensured that it works on dev, the typical way of doing things would be to add that manage.py command
to the deploy instructions for the relevant tag.
The engineer responsible for the tag would run the command on stage,
then SRE would run it in production on deploy.

## Cleanup

After a switch is enabled for all users and is no longer needed, you can remove it by:

1. Deleting all code referring to the switch.
2. adding a migration to remove the flag.

[devops]: https://mozilla-hub.atlassian.net/wiki/spaces/FDPDT/pages/98795521/DevOps#How-to-run-./manage.py-commands-in-an-environment "Devops"
[waffle-cli]: https://waffle.readthedocs.io/en/stable/usage/cli.html#switches "Waffle CLI"
