require "yaml"

# Load up our vagrant config files -- vagrantconfig.yaml first
_config = YAML.load(File.open(File.join(File.dirname(__FILE__),
                    "vagrantconfig.yaml"), File::RDONLY).read)

# Local-specific/not-git-managed config -- vagrantconfig_local.yaml
begin
    _config.merge!(YAML.load(File.open(File.join(File.dirname(__FILE__),
                   "vagrantconfig_local.yaml"), File::RDONLY).read))
rescue Errno::ENOENT # No vagrantconfig_local.yaml found -- that's OK; just
                     # use the defaults.
end

CONF = _config
MOUNT_POINT = '/home/vagrant/project'

Vagrant::Config.run do |config|
    config.vm.box = "zamboni-full"
    config.vm.box_url = "http://people.mozilla.com/~kmcmillan/zamboni.box"
    # This is the stock VM:
    # config.vm.box_url = "http://files.vagrantup.com/lucid32.box"

    # TODO(Kumar) figure out a way to forward port 80, as requested from the
    # guest, to 8000 on the host. This apparently doesn't do that :/
    # config.vm.forward_port(80, 8000)
    # config.vm.forward_port("web", 80, 8000)  # old 0.8.* way

    # Increase vagrant's patience during hang-y CentOS bootup
    # see: https://github.com/jedi4ever/veewee/issues/14
    config.ssh.max_tries = 50
    config.ssh.timeout   = 300

    # nfs needs to be explicitly enabled to run.
    if CONF['nfs'] == false or RUBY_PLATFORM =~ /mswin(32|64)/
        config.vm.share_folder("v-root", MOUNT_POINT, ".")
    else
        config.vm.share_folder("v-root", MOUNT_POINT, ".", :nfs => true)
    end

    # For convenience add something like this to /etc/hosts: 33.33.33.24 z.local
    config.vm.network :hostonly, "33.33.33.24"
    #config.vm.network "33.33.33.24"  # old 0.8.* way

    config.vm.provision :puppet do |puppet|
        puppet.manifests_path = "vagrant/manifests"
        puppet.manifest_file  = "vagrant.pp"
    end
end
