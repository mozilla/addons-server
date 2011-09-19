# stage {"pre": before => Stage["main"]} class {'apt': stage => 'pre'}

# Commands to run before all others in puppet.
class init {
    group { "puppet":
        ensure => "present",
    }

    case $operatingsystem {
        ubuntu: {
            exec { "update_apt":
                command => "sudo apt-get update"
            }

            # Provides "add-apt-repository" command, useful if you need
            # to install software from other apt repositories.
            package { "python-software-properties":
                ensure => present,
                require => [
                    Exec['update_apt'],
                ];
            }

            exec { "add_java_repo":
                # For sun java:
                command => 'sudo add-apt-repository "deb http://archive.canonical.com/ lucid partner"',
                require => Package["python-software-properties"]
            }

            exec { "init_java_repo":
                # Bah, this is lame.
                command => "sudo apt-get update",
                require => Exec['add_java_repo']
            }
        }
    }

    # If you haven't created a custom pp file, create one from dist.
    file { "$PROJ_DIR/vagrant/manifests/classes/custom.pp":
        ensure => file,
        source => "$PROJ_DIR/vagrant/manifests/classes/custom-dist.pp",
        replace => false;
    }
}
