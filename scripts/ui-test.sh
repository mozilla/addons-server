#!/bin/sh
echo 127.0.0.1 olympia.dev | tee -a /etc/hosts
yum -y install curl
curl https://raw.githubusercontent.com/creationix/nvm/v0.30.2/install.sh > install-nvm.sh
sh install-nvm.sh
source ~/.bash_profile
nvm install node
unset NPM_CONFIG_PREFIX
pip install tox
tox -e ui-tests
