#!/bin/bash
default_versions_future="beta aurora nightly ux"
default_versions_current="11.0"
default_versions_past="2.0.0.20 3.0.19 3.5.9 3.6.28 4.0.1 5.0.1 6.0.2 7.0.1 8.0.1 9.0.1 10.0.2"

default_versions="${default_versions_past} ${default_versions_current} ${default_versions_future}"
tmp_directory="/tmp/firefoxes/"
bits_directory="${tmp_directory}bits/"
install_directory="/Applications/Firefoxes/"

locale_default="en-GB"

# Don't edit below this line (unless you're adding new version cases in get_associated_information)

versions="${1:-$default_versions}"
ftp_root=""
dmg_file=""
sum_file=""
sum_file_type=""
sum_of_dmg=""
sum_expected=""
binary=""
short_name=""
nice_name=""
vol_name_default="Firefox"
release_name_default="Firefox"
release_type=""
binary_folder="/Contents/MacOS/"

locale=$2

if [[ "${3}" == "prompt" ]]
    then
    no_prompt="false"
else
    no_prompt="true"
fi

get_associated_information(){
    # Reset everything
    vol_name=$vol_name_default
    release_name=$release_name_default
    autoupdate=""
    future=""

    case $1 in
        2.0.0.20)
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/releases/2.0.0.20/"
            dmg_file="Firefox 2.0.0.20.dmg"
            sum_file="MD5SUMS"
            sum_file_type="md5"
            binary="firefox-bin"
            short_name="fx2"
            nice_name="Firefox 2.0"

            firebug_version="1.3.1"
            firebug_root="http://getfirebug.com/releases/firebug/1.3/"
            firebug_file="firebug-1.3.1.xpi"
        ;;
        3.0.19)
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/releases/3.0.19-real-real/"
            dmg_file="Firefox 3.0.19.dmg"
            sum_file="MD5SUMS"
            sum_file_type="md5"
            binary="firefox-bin"
            short_name="fx3"
            nice_name="Firefox 3.0"

            firebug_version="1.3.4b2"
            firebug_root="http://getfirebug.com/releases/firebug/1.3/"
            firebug_file="firebug-1.3.4b2.xpi"
        ;;
        3.5.9)
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/releases/3.5.9/"
            dmg_file="Firefox 3.5.9.dmg"
            sum_file="MD5SUMS"
            sum_file_type="md5"
            binary="firefox-bin"
            short_name="fx35"
            nice_name="Firefox 3.5"

            firebug_version="1.5.4"
            firebug_root="http://getfirebug.com/releases/firebug/1.5/"
            firebug_file="firebug-1.5.4.xpi"
        ;;
        3.6.28)
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/releases/3.6.28/"
            dmg_file="Firefox 3.6.28.dmg"
            sum_file="MD5SUMS"
            sum_file_type="md5"
            binary="firefox-bin"
            short_name="fx36"
            nice_name="Firefox 3.6"

            firebug_version="1.7.3"
            firebug_root="http://getfirebug.com/releases/firebug/1.7/"
            firebug_file="firebug-1.7.3.xpi"
        ;;
        4.0.1)
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/releases/4.0.1/"
            dmg_file="Firefox 4.0.1.dmg"
            sum_file="MD5SUMS"
            sum_file_type="md5"
            binary="firefox-bin"
            short_name="fx4"
            nice_name="Firefox 4.0"

            firebug_version="1.8.0b7"
            firebug_root="http://getfirebug.com/releases/firebug/1.8/"
            firebug_file="firebug-1.8.0b7.xpi"
        ;;
        5.0.1)
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/releases/5.0.1/"
            dmg_file="Firefox 5.0.1.dmg"
            sum_file="MD5SUMS"
            sum_file_type="md5"
            binary="firefox-bin"
            short_name="fx5"
            nice_name="Firefox 5.0"

            firebug_version="1.9.1"
            firebug_root="http://getfirebug.com/releases/firebug/1.9/"
            firebug_file="firebug-1.9.1.xpi"
        ;;
        6.0.2)
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/releases/6.0.2/"
            dmg_file="Firefox 6.0.2.dmg"
            sum_file="MD5SUMS"
            sum_file_type="md5"
            binary="firefox-bin"
            short_name="fx6"
            nice_name="Firefox 6.0"

            firebug_version="1.9.1"
            firebug_root="http://getfirebug.com/releases/firebug/1.9/"
            firebug_file="firebug-1.9.1.xpi"
        ;;
        7.0.1)
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/releases/7.0.1/"
            dmg_file="Firefox 7.0.1.dmg"
            sum_file="MD5SUMS"
            sum_file_type="md5"
            binary="firefox"
            short_name="fx7"
            nice_name="Firefox 7.0"

            firebug_version="1.9.1"
            firebug_root="http://getfirebug.com/releases/firebug/1.9/"
            firebug_file="firebug-1.9.1.xpi"
        ;;
        8.0.1)
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/releases/8.0.1/"
            dmg_file="Firefox 8.0.1.dmg"
            sum_file="MD5SUMS"
            sum_file_type="md5"
            binary="firefox"
            short_name="fx8"
            nice_name="Firefox 8.0"

            firebug_version="1.9.1"
            firebug_root="http://getfirebug.com/releases/firebug/1.9/"
            firebug_file="firebug-1.9.1.xpi"
        ;;
        9.0.1)
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/releases/9.0.1/"
            dmg_file="Firefox 9.0.1.dmg"
            sum_file="MD5SUMS"
            sum_file_type="md5"
            binary="firefox"
            short_name="fx9"
            nice_name="Firefox 9.0"

            firebug_version="1.9.1"
            firebug_root="http://getfirebug.com/releases/firebug/1.9/"
            firebug_file="firebug-1.9.1.xpi"
        ;;
        10.0.2)
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/releases/10.0.2/"
            dmg_file="Firefox 10.0.2.dmg"
            sum_file="MD5SUMS"
            sum_file_type="md5"
            binary="firefox"
            short_name="fx10"
            nice_name="Firefox 10.0"

            firebug_version="1.9.1"
            firebug_root="http://getfirebug.com/releases/firebug/1.9/"
            firebug_file="firebug-1.9.1.xpi"
        ;;
        11.0)
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/releases/11.0/"
            dmg_file="Firefox 11.0.dmg"
            sum_file="MD5SUMS"
            sum_file_type="md5"
            binary="firefox"
            short_name="fx11"
            nice_name="Firefox 11.0"

            firebug_version="1.9.1"
            firebug_root="http://getfirebug.com/releases/firebug/1.9/"
            firebug_file="firebug-1.9.1.xpi"
        ;;        
        beta)
            # This seems a bit flaky

            release_type="beta"
            # future="true" # Even though it's technically future, the file structure is the same as non-future
            autoupdate="true"
            ftp_candidates="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/candidates/"

            if [[ $versions != 'status' ]]
                then
                candidates_folder=`curl --silent -L ${ftp_candidates} | sort -n | tail -n1`
                build_folder=`curl --silent -L ${ftp_candidates}${candidates_folder}/ | sort -n | tail -n1`

                ftp_root="${ftp_candidates}${candidates_folder}/${build_folder}/"

                dmg_file=`curl --silent -L ${ftp_root}mac/${locale}/ | grep ".dmg" | sed "s/^.\{56\}//"`
                sum_file_tmp=`curl --silent -L ${ftp_root}mac/${locale}/ | grep ".checksums$" | sed "s/^.\{56\}//"`
                sum_file_folder="mac/${locale}/"
                sum_file="${sum_file_tmp}"
                sum_file_type="md5"
            fi

            binary="firefox"
            short_name="fxb"
            nice_name="Firefox Beta"

            firebug_version="1.9.1"
            firebug_root="http://getfirebug.com/releases/firebug/1.9/"
            firebug_file="firebug-1.9.1.xpi"
        ;;
        aurora)
            release_type="aurora"
            future="true"
            autoupdate="true"
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/nightly/latest-mozilla-aurora/"

            if [[ $versions != 'status' ]]
                then
                dmg_file=`curl --silent -L ${ftp_root} | grep ".mac.dmg" | sed "s/^.\{56\}//"`
                sum_file=`echo ${dmg_file} | sed "s/\.dmg/\.checksums/"`
                sum_file_type="sha512"
            fi

            binary="firefox"
            short_name="fxa"
            nice_name="Firefox Aurora"
            vol_name="Aurora"
            release_name="FirefoxAurora"

            firebug_version="1.9.1"
            firebug_root="http://getfirebug.com/releases/firebug/1.9/"
            firebug_file="firebug-1.9.1.xpi"
        ;;
        nightly)
            release_type="nightly"
            future="true"
            autoupdate="true"
            ftp_root="ftp://ftp.mozilla.org//pub/mozilla.org/firefox/nightly/latest-trunk/"

            if [[ $versions != 'status' ]]
                then
                dmg_file=`curl --silent -L ${ftp_root} | grep ".mac.dmg" | sed "s/^.\{56\}//"`
                sum_file=`echo ${dmg_file} | sed "s/\.dmg/\.checksums/"`
                sum_file_type="sha512"
            fi

            binary="firefox"
            short_name="fxn"
            nice_name="Firefox Nightly"
            vol_name="Nightly"
            release_name="FirefoxNightly"

            firebug_version="1.9.1"
            firebug_root="http://getfirebug.com/releases/firebug/1.9/"
            firebug_file="firebug-1.9.1.xpi"
        ;;
        ux)
            release_type="ux"
            future="true"
            autoupdate="true"
            ftp_root="ftp://ftp.mozilla.org/pub/mozilla.org/firefox/nightly/latest-ux/"

            if [[ $versions != 'status' ]]
                then
                dmg_file=`curl --silent -L ${ftp_root} | grep ".mac.dmg" | sed "s/^.\{56\}//"`
                sum_file=`echo ${dmg_file} | sed "s/\.dmg/\.checksums/"`
                sum_file_type="sha512"
            fi

            binary="firefox"
            short_name="fxux"
            nice_name="Firefox UX Nightly"
            vol_name="UX"
            release_name="FirefoxUX"

            firebug_version="1.9.1"
            firebug_root="http://getfirebug.com/releases/firebug/1.9/"
            firebug_file="firebug-1.9.1.xpi"
        ;;
        *)
            error "  Invalid version specified!\n\n  Please choose one of:\n  all all_past all_future current $default_versions\n\n"
            error "  To see which versions you have installed, type:\n  ./bootstrap.sh status"
            exit 1
        ;;
    esac
}
setup_dirs(){
    if [[ ! -d "$tmp_directory" ]]
        then
        mkdir -p "$tmp_directory"
    fi
    if [[ ! -d "$bits_directory" ]]
        then
        mkdir -p "$bits_directory"
    fi
    if [[ ! -d "$install_directory" ]]
        then
        mkdir -p "$install_directory"
    fi
}
get_bits(){
    log "Downloading bits"
    current_dir=`pwd`
    cd "$bits_directory"
    if [[ ! -f "setfileicon" ]]
        then
        curl -C -L --silent "https://raw.github.com/omgmog/install-all-firefox/master/bits/setfileicon" -o "setfileicon"
        chmod +x setfileicon
    fi
    if [[ ! -f "${short_name}.png" ]]
        then
        new_icon="true"
        icon_file="${current_dir}/bits/${short_name}.png"

        # If file exists locally, use it
        if [[ -f $icon_file ]]
            then
            cp -r $icon_file "${short_name}.png"
        else
            curl -C -L --silent "https://raw.github.com/omgmog/install-all-firefox/master/bits/${short_name}.png" -o "${short_name}.png"
        fi
    fi
    if [[ ! -f "${short_name}.icns" || $new_icon == "true" ]]
        then
        sips -s format icns "${short_name}.png" --out "${short_name}.icns" > /dev/null
    fi
    if [[ ! -f "${install_directory}{$nice_name}.app/Icon" ]]
        then
        if [[ ! -f "fxfirefox-folder.png" ]]
            then
            curl -C -L --silent "https://raw.github.com/omgmog/install-all-firefox/master/bits/fxfirefox-folder.png" -o "fxfirefox-folder.png"
        fi
        if [[ ! -f "fxfirefox-folder.icns" ]]
            then
            sips -s format icns "fxfirefox-folder.png" --out "fxfirefox-folder.icns"
        fi
        ./setfileicon "fxfirefox-folder.icns" "${install_directory}"
    fi
}
check_dmg(){
    if [[ ! -f "${tmp_directory}/${dmg_file}" ]]
        then
        log "Downloading ${dmg_file}"
        download_dmg
    else
        get_sum_file
        case $sum_file_type in
            md5)
                sum_of_dmg=`md5 -q "${tmp_directory}${dmg_file}"`
                sum_expected=`cat "${sum_file}-${short_name}" | grep "${locale}/${dmg_file}" | cut -c 1-32`
            ;;
            sha512)
                sum_of_dmg=`openssl dgst -sha512 "${tmp_directory}${dmg_file}" | sed "s/^.*\(.\{128\}\)$/\1/"`
                sum_expected=`cat "${sum_file}-${short_name}" | grep "${sum_of_dmg}" | cut -c 1-128`
            ;;
            *)
                error "✖ Invalid sum type specified!"
            ;;
        esac

        if [[ "${sum_expected}" == *"${sum_of_dmg}"* ]]
            then
            log "✔ ${sum_file_type} of ${dmg_file} matches"
        else
            error "✖ ${sum_file_type} of ${dmg_file} doesn't match!"
            log "Redownloading.\n"
            download_dmg
        fi
    fi
}
get_sum_file(){
    cd "${tmp_directory}"
    curl -C -L --silent "${ftp_root}${sum_file_folder}${sum_file}" -o "${sum_file}-${short_name}"
}
download_dmg(){
    cd "${tmp_directory}"
    if [[ "${future}" == "true" ]]
        then
        dmg_url="${ftp_root}${dmg_file}"
    else
        dmg_url="${ftp_root}mac/$locale/${dmg_file}"
    fi
    if ! curl -C -L --silent "${dmg_url}" -o "${dmg_file}"
        then
        error "✖ Failed to download ${dmg_file}!"
    fi
}
download_firebug(){
    cd "${tmp_directory}"
    if [[ ! -f "${tmp_directory}${firebug_file}" ]]
        then
        if ! curl -C -L --silent "${firebug_root}${firebug_file}" -o "${firebug_file}"
            then
            error "✖ Failed to download ${firebug_file}"
        else
            log "✔ Downloaded ${firebug_file}"
        fi
    fi
}
prompt_firebug(){
    if [ "${no_prompt}" == "false" ]
        then
        log "Install Firebug ${firebug_version} for ${nice_name}? [y/n]"
        read user_choice
        choice_made="false"
        while [[ "$choice_made" == "false" ]]
        do
            case "$user_choice" in
                "y")
                    choice_made="true"
                    download_firebug
                    install_firebug
                ;;
                "n")
                    choice_made="true"
                ;;
            esac
        done
    else
        download_firebug
        install_firebug
    fi


}
install_firebug(){
    if [[ -f "${install_directory}${nice_name}.app${binary_folder}${binary}" ]]
        then
        ext_dir=`cd $HOME/Library/Application\ Support/Firefox/Profiles/;cd \`ls -1 | grep ${short_name}\`; pwd`
        cd "${ext_dir}"
        if [[ ! -d "extensions" ]]
            then
            mkdir "extensions"
        fi
        cd "extensions"
        ext_dir=`pwd`

        cp -r "${tmp_directory}${firebug_file}" "${ext_dir}"
        log "✔ Installed Firebug ${firebug_version}"
    else
        error "${nice_name} not installed so we can't install Firebug ${firebug_version}!"
    fi
}
mount_dmg(){
    hdiutil attach -plist -nobrowse -readonly -quiet "${dmg_file}" > /dev/null
}
unmount_dmg(){
    if [[ -d "/Volumes/${vol_name}" ]]
        then
        hdiutil detach "/Volumes/${vol_name}" -force > /dev/null
    fi
}
install_app(){
    if [[ -d "${install_directory}${nice_name}.app" ]]
        then

        if [ "${no_prompt}" == "false" ]
            then
            log "Delete your existing ${nice_name}.app and install again? [y/n]"
            read user_choice
            choice_made="false"
            while [[ "$choice_made" == "false" ]]
            do
                case "$user_choice" in
                    "y")
                        choice_made="true"
                        log "Reinstalling ${nice_name}.app"
                        remove_app
                        process_install
                    ;;
                    "n")
                        choice_made="true"
                        log "Skipping installation of ${nice_name}.app"
                    ;;
                    *)
                        error "Please enter 'y' or 'n'"
                        read user_choice
                    ;;
                esac
            done
        else
            remove_app
            process_install
        fi
    else
        process_install
    fi
}
remove_app(){
    if rm -rf "${install_directory}${nice_name}.app"
        then
        log "✔ Removed ${install_directory}${nice_name}.app"
    else
        error "✖ Could not remove ${install_directory}${nice_name}.app!"
    fi
}
process_install(){
    cd "/Volumes/${vol_name}"
    if cp -r "${release_name}.app/" "${install_directory}${nice_name}.app/"
        then
        log "✔ Installed ${nice_name}.app"
    else
        unmount_dmg
        error "✖ Could not install ${nice_name}.app!"
    fi
    unmount_dmg
    create_profile
    modify_launcher
    install_complete
}
create_profile(){
    if exec "${install_directory}${nice_name}.app${binary_folder}${binary}" -CreateProfile "${short_name}" &> /dev/null &
        then
        log "✔ Created profile '${short_name}' for ${nice_name}"
    else
        error "✖ Could not create profile '${short_name}' for ${nice_name}"
    fi
}
modify_launcher(){
    plist_old="${install_directory}${nice_name}.app/Contents/Info.plist"
    plist_new="${tmp_directory}Info.plist"
    sed -e "s/${binary}/${binary}-af/g" "${plist_old}" > "${plist_new}"
    mv "${plist_new}" "${plist_old}"

    echo -e "#!/bin/sh\n\"${install_directory}${nice_name}.app${binary_folder}${binary}\" -no-remote -P \"${short_name}\" &" > "${install_directory}${nice_name}.app${binary_folder}${binary}-af"
    chmod +x "${install_directory}${nice_name}.app${binary_folder}${binary}-af"

    if [[ $autoupdate != "true" ]]
        then
        prefs_previous="\n pref(\"app.update.auto\",false);\n pref(\"app.update.enabled\",false);"
    fi

    echo -e "pref(\"browser.shell.checkDefaultBrowser\", false);${prefs_previous}\n pref(\"browser.startup.homepage\",\"about:blank\");\n pref(\"browser.shell.checkDefaultBrowser\", false)" > "${install_directory}${nice_name}.app${binary_folder}defaults/pref/macprefs.js"

    cd "${bits_directory}"
    ./setfileicon "${short_name}.icns" "${install_directory}/${nice_name}.app/"
}
install_complete(){
    log "✔ Install complete!"
}
error(){
    printf "\n\033[31m$*\033[00m"
    return 0
}
log(){
    printf "\n\033[32m$*\033[00m\n"
    return $?
}

# Replace special keywords with actual versions (duplicates are okay; it'll work fine)
versions=${versions/all_future/${default_versions_future}}
versions=${versions/all_past/${default_versions_past}}
versions=${versions/all/${default_versions}}
versions=${versions/current/${default_versions_current}}

if [[ $versions == 'status' ]]
    then
    printf "The versions in \033[32mgreen\033[00m are installed:\n"
    for VERSION in $default_versions
    do
        get_associated_information $VERSION
        if [[ -d "${install_directory}${nice_name}.app" ]]
            then
            printf "\n\033[32m - ${nice_name} ($VERSION)\033[00m"
        else
            printf "\n\033[31m - ${nice_name} ($VERSION)\033[00m"
        fi
    done
    printf "\n\nTo install, type \033[1m./bootstrap.sh [version]\033[22m, \nwith [version] being the number or name in parentheses\n\n"
    exit 1
fi

get_locale() {
    all_locales=" af ar be bg ca cs da de el en-GB en-US es-AR es-ES eu fi fr fy-NL ga-IE he hu it ja-JP-mac ko ku lt mk mn nb-NO nl nn-NO pa-IN pl pt-BR pt-PT ro ru sk sl sv-SE tr uk zh-CN zh-TW "
    lang=`echo ${LANG/_/-} | sed 's/\..*//'`

    if [[ -z $locale ]]
    then
        if [[ $all_locales == *" $lang "* ]]
            then
            locale=$lang
            echo "We detected your locale as ${lang}."
        else
            locale=$locale_default
            echo "We couldn't guess your locale so we're falling back on ${locale_default}."
        fi
        echo -e "If this is wrong, use './bootstrap.sh [version] [locale]' to specify the locale.\n"
    fi
}
clean_up() {
    log "Delete all files from temp directory (${tmp_directory})? [y/n]"
    read user_choice
    choice_made="false"
    while [[ "$choice_made" == "false" ]]
    do
        case "$user_choice" in
            "y")
                choice_made="true"
                log "Deleting temp directory (${tmp_directory})!"
                rm -rf ${tmp_directory}
            ;;
            "n")
                choice_made="true"
                log "Keeping temp directory (${tmp_directory}), though it will be deleted upon reboot!\n"
            ;;
            *)
                error "Please enter 'y' or 'n'"
                read user_choice
            ;;
        esac
    done
    return 0
}

if [ `uname -s` != "Darwin" ]
    then
    error "This script is designed to be run on OS X\nExiting...\n"
    exit 0
fi

get_locale

for VERSION in $versions
do
    get_associated_information $VERSION
    log "====================\nInstalling ${nice_name}"
    setup_dirs
    get_bits
    check_dmg
    mount_dmg
    install_app
    unmount_dmg
    prompt_firebug
done

clean_up