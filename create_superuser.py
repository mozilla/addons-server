import json
import os
from StringIO import StringIO

import django
from django.core.management import call_command

from olympia.users.models import UserProfile

django.setup()

out = StringIO()
try:
    call_command(
        'createsuperuser',
        interactive=False,
        username='uitest',
        email='uitest@restmail.com',
        add_to_supercreate_group=True,
        stdout=out)
except(django.db.utils.IntegrityError):
    print('Superuser for ui testing has already been created.')
finally:
    exit()


user = UserProfile.objects.get(username='uitest')
assert user.email == 'uitest@restmail.com'
assert user.groups.filter(rules='Accounts:SuperCreate').exists()

response = json.loads(out.getvalue())

# Create json object for api keys
variables = {}

variables['api'] = []
variables['api'].append({
    'jwt_issuer': response['api-key'],
    'jwt-secret': response['api-secret']
})

# export json object
with open('tests/ui/variables.json', 'w') as outfile:
    json.dump(variables, outfile, indent=4)
os.system("exit")
