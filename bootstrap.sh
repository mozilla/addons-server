#!/bin/bash
# Bootstrap to check for script updates before running ./install-all-firefox.sh

error(){
    printf "\n\033[31m$*\033[00m"
    return 0
}
if [ `uname -s` != "Darwin" ]
    then
    error "This script is designed to be run on OS X\nExiting...\n"
    exit 0
fi

local_script_md5=`md5 -q install-all-firefox.sh`
remote_script_md5=''

while [ "${remote_script_md5}" == "" ]
do
	if curl -C -L "https://raw.github.com/omgmog/install-all-firefox/master/install-all-firefox.sh" -o "/tmp/install-all-firefox.sh"
		then
		chmod +x "/tmp/install-all-firefox.sh"
		remote_script_md5=`md5 -q /tmp/install-all-firefox.sh`
	fi
done

if [ ! "${local_script_md5}" == "${remote_script_md5}" ]
	then
	cp /tmp/install-all-firefox.sh ./install-all-firefox.sh
	chmod +x ./install-all-firefox.sh
fi

./install-all-firefox.sh ${*}