class settings_local {
    file { "$PROJ_DIR/settings_local.py":
        ensure => file,
        source => "$PROJ_DIR/docs/settings/settings_local.dev.py",
        replace => false;
    } 
}
