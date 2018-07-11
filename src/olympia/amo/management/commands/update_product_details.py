"""
Overwriting the upstream update_product_details command to set
`requires_system_checks = False` instead to support Docker builds without a
database.

The problem is that the upstream update_product_details command only
disables a few checks but not all of them. We don't run a MySQL database
while building the docker image and when Django runs db-field checks
(which it does by default since Django 1.10) it requires a working MySQL
connection.

Fix for https://github.com/mozilla/addons-server/issues/8822
"""
from product_details.management.commands import update_product_details


class Command(update_product_details.Command):
    requires_system_checks = False
