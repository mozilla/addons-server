# Zamboni needs to allow for long-running commands.
# This disables the SSH timeout.
class fix_ssh {
    file { "/etc/ssh/ssh_config":
        ensure => file,
        source => "$PROJ_DIR/vagrant/files/etc/ssh/ssh_config",
        owner => "root",
        mode => 644,
        replace => true;
    }

    exec { "restart-ssh":
        command => "sudo /etc/init.d/ssh restart",
        require => File["/etc/ssh/ssh_config"]
    }
}
