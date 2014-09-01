# playdoh-specific commands that get zamboni all going so you don't
# have to.

# TODO: Make this rely on things that are not straight-up exec.
class zamboni {
    package { "wget":
        ensure => installed;
    }

    exec { "create_mysql_database":
        command => "mysqladmin -uroot create $DB_NAME",
        unless  => "mysql -uroot -B --skip-column-names -e 'show databases' | /bin/grep '$DB_NAME'",
        require => File["$PROJ_DIR/settings.py"]
    }

    exec { "grant_mysql_database":
        command => "mysql -uroot -B -e'GRANT ALL PRIVILEGES ON $DB_NAME.* TO $DB_USER@localhost # IDENTIFIED BY \"$DB_PASS\"'",
        unless  => "mysql -uroot -B --skip-column-names mysql -e 'select user from user' | grep '$DB_USER'",
        require => Exec["create_mysql_database"];
    }

    exec { "fetch_landfill_sql":
        cwd => "$PROJ_DIR",
        command => "wget -P /tmp https://landfill-addons.allizom.org/db_data/landfill-`date +%Y-%m-%d`.sql.gz",
        require => [
            Package["wget"],
            Exec["grant_mysql_database"]
        ];
    }

    exec { "load_data":
        cwd => "$PROJ_DIR",
        command => "zcat /tmp/landfill-`date +%Y-%m-%d`.sql.gz | mysql -u$DB_USER $DB_NAME",
        require => [
            Exec["fetch_landfill_sql"]
        ];
    }

    # TODO(Kumar) add landfile files as well.

    exec { "remove_site_notice":
        command => "mysql -uroot -e\"delete from config where \\`key\\`='site_notice'\" $DB_NAME",
        require => Exec["load_data"]
    }
}
