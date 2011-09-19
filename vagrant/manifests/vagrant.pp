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
    class {
        init: before => Class[mysql];
        mysql: before  => Class[python];
        python: before => Class[redis];
        # apache: before => Class[zamboni];
        redis: before => Class[zamboni];
        elasticsearch: ;
        zamboni: ;
        custom: ;
    }
}

include dev
