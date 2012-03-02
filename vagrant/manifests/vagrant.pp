#
# Playdoh puppet magic for dev boxes
#
import "classes/*.pp"

$PROJ_DIR = "/home/vagrant/project"

# You can make these less generic if you like, but these are box-specific
# so it's not required.
# The db user does not require a password.
$DB_NAME = "zamboni"
$DB_USER = "root"

Exec {
    path => "/usr/local/bin:/usr/bin:/usr/sbin:/sbin:/bin",
}

class dev {

    # We need to use a custom VM box until the Net::SSH bug is fixed:
    # https://github.com/mitchellh/vagrant/issues/516
    # The custom box was provisioned with the commented out commands.
    # Once the bug is fixed we can go back to the stock box and activate
    # the full suite of provisioning.

    class {
        # init: before => Class[mysql];
        # mysql: before  => Class[python];
        # python: before => Class[zamboni];
        # # apache: before => Class[zamboni];
        # redis: before => Class[zamboni];
        # elasticsearch: before => Class[zamboni];
        # zamboni: before => Class[migrate];
        # migrate: before => Class[custom];
        init: before => Class[zamboni_plus];
        zamboni_plus: before => Class[custom];
        custom: ;
        # On startup, bin/start.sh runs which does the db migrations
    }
}

include dev
