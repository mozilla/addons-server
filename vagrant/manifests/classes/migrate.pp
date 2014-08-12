# Migrate the database
class migrate {
    package { ["git-core", "python2.6"]:
        ensure => installed;
    }

    # Skip this migration because it won't succeed without indexes but you
    # can't build indexes without running migrations :(
    file { "$PROJ_DIR/migrations/264-locale-indexes.py":
        content => "def run(): pass",
        replace => true
    }

    exec { "sql_migrate":
        cwd => "$PROJ_DIR",
        command => "schematic migrations/",
        logoutput => true,
        require => [
            # Service["mysql"],
            Package["python2.6"],
            File["$PROJ_DIR/settings.py"],
            File["$PROJ_DIR/migrations/264-locale-indexes.py"],
            # Exec["fetch_landfill_sql"],
            # Exec["load_data"]
        ];
    }

    exec { "restore_migration_264":
        cwd => "$PROJ_DIR",
        command => "git checkout migrations/264-locale-indexes.py",
        require => [Exec["sql_migrate"], Package["git-core"]]
    }
}
