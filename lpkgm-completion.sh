#!/usr/bin/env bash

: "${CVMFS_ROOT:=/cvmfs/na64.cern.ch/sft/}"
: "${LPKGM_SETTINGS_FILE:=./lpkgm/na64-cvmfs-settings.json}"

_platforms_list() {
    find $CVMFS_ROOT -maxdepth 3 -type d -and -name .packages -print0 | sort --zero-terminated |
    while read -r -d '' pkgDir ; do
        platformDir=$(readlink -f $pkgDir/..)
	platformID=${platformDir#"${CVMFS_ROOT}"}
	echo "$platformID"
    done
}

_platforms_opts_list() {
    for plat in $(_platforms_list) ; do
        echo "-Dplatform=${plat}"
    done
}

_def_names() {
    echo -e "-Dplatform=\n-Dplatform_="
}

_list_packages_to_install() {
    if [ ! -f ${LPKGM_SETTINGS_FILE} ] ; then
        return 0
    fi
    jq --raw-output '.packages|keys[]' ${LPKGM_SETTINGS_FILE}
}

_list_versions_to_install() {
    local platform=$1
    local pkgName=$2
    # ... TODO
    #echo -e "1.2.3-dbg\n1.2.4-opt"
}

_list_installed_packages() {
    local platform=$1
    local pkgDir="${CVMFS_ROOT}/${platform}/.packages"
    if [ ! -d $pkgDir ] ; then
        return 0
    fi
    find "${pkgDir}" -maxdepth 1 -type d -and -not -name '.*' -and -not -empty -exec basename {} \; 
}

_list_installed_versions() {
    local platform=$1
    local pkgName=$2
    local pkgDir="${CVMFS_ROOT}/${platform}/.packages/${pkgName}"
    if [ ! -d ${pkgDir} ] ; then
        return 0
    fi
    find ${pkgDir} -maxdepth 1 -type f -and -not -name '.*' -exec jq --raw-output '.version.fullVersion' {} \;
}

_lpkgm_completions() {
    # NOTE: native bash completions forces space surrounding certain
    # characters, so we do not rely here on COMP_WORDS/COMP_CWORD and
    # do the line splitting on our own
    local words  # array of space-separated words
    local cword  # current (to-complete) word from space-delimited list
    local scmd   # command in use (can be empty)
    local cPlatform  # current platform (can be empty)
    local pkgName  # package name, name pattern or empty
    local pkgVer  # package version, version pattern or empty
    local ignoreNext=false  # internal flag meaning "ignore next arg)
    local compCWord="${COMP_WORDS[$COMP_CWORD]}"  # bash completion current word
    # truncate line up to the position of our cursor, transform the result
    # into an array
    words=(${COMP_LINE:0:$COMP_POINT})
    # get the word under cursor
    cword=${words[-1]}
    # dbg:
    #echo -e "\n\"${COMP_LINE}\"\n-> \"${opts[@]}}\", \"${copt}\""  # XXX
    for ccword in ${words[@]} ; do
        if [ -z "$ccword" ] ; then
            continue
        fi
        if [ "$ignoreNext" = true ] ; then
            ignoreNext=false
            continue
        fi
        # check if arg is platform
        if [[ "$ccword" =~ -Dplatform=.+ ]] ; then  # platform defined
            cPlatform=${ccword#*=}
            #echo "xxx cPlatform=$cPlatform"
            continue
        fi
        # check if arg is subcommand
        case "$ccword" in  # command defined
            install|add)
                scmd=install
                continue
        	;;
            remove|delete|uninstall|rm)
                scmd=remove
                continue
        	;;
            show|inspect|list)
                scmd=show
                continue
        	;;
        esac
        # check if arg starts with `-' or `--' and set "ignore next" flag if
        # need
        if [[ "$ccword" =~ ^-.$ ]] \
        || [[ "$ccword" =~ ^--[^=]+$ ]] ; then
            ignoreNext=true
            continue
        fi
        if [ ! -z "$scmd" ] ; then
            # otherwise, consider it to be positional arguments: 1) pkg name,
            # 2) pkg version
            if [ -z "$pkgName" ] ; then
                pkgName="$ccword"
                continue
            elif [ -z "$pkgVer" ] ; then
                pkgVer="$ccword"
                continue
            fi
        fi
        # do nothing otherwise, ignore word
    done
    if [ "$ignoreNext" = true ] ; then
        local files=("/var/log/app/$2"*)
        [[ -e ${files[0]} ]] && COMPREPLY=( "${files[@]##*/}" )
        return 0
    fi
    # First, treat a very special case when word to be completed
    # is "-Dplatform=...".
    # In this way bash comletion will split it onto ("-Dplaform" "=" "...")
    # making interpret logic very complicated. In this case we propose bash
    # completion with list of platforms to use
    if [[ "$cword" == -Dplatform* ]] && [[ ! -z "$compCWord" ]] ; then
        if [[ "$compCWord" == "=" ]] ; then
            COMPREPLY=($(_platforms_list))
        else
            COMPREPLY=($(compgen -W "$(_platforms_list)" -- "${COMP_WORDS[$COMP_CWORD]}"))
        fi
        return 0
    fi
    # if platform is not set at all
    if [ -z "$cPlatform" ] ; then  # current platform not set
        COMPREPLY=($(compgen -W "$(_platforms_opts_list)" -- "${COMP_WORDS[$COMP_CWORD]}"))
        return 0
    elif [ -z "$scmd" ] ; then  # sub-command not set
        COMPREPLY=($(compgen -W "install remove show" -- "${COMP_WORDS[$COMP_CWORD]}"))
        return 0
    else
        # depending on sub-command completion differ
        case $scmd in
            install|add)
                # rely on available packages from config
                if [ -z "${pkgName}" ] || [ "${pkgName}" = "${compCWord}" ] ; then
                    # version not specified -- complete with available pkgs
                    COMPREPLY=($(compgen -W "$(_list_packages_to_install)" -- "$compCWord"))
                elif [ -z "${pkgVer}" ] || [ "${pkgVer}" = "${compCWord}" ] ; then
                    # version given -- complete with available versions
                    COMPREPLY=($(compgen -W "$(_list_versions_to_install $cPlatform $pkgName)" -- "$compCWord"))
                fi
                ;;
            remove|delete|uninstall|rm|show|inspect|list)
                # consider installed packages to append names and versions
                if [ -z "${pkgName}" ] || [ "${pkgName}" = "${compCWord}" ] ; then
                    # version not specified -- complete with available pkgs
                    COMPREPLY=($(compgen -W "$(_list_installed_packages $cPlatform)" -- "$compCWord"))
	    	elif [ -z "${pkgVer}" ] || [ "${pkgVer}" = "${compCWord}" ] ; then
                    # version given -- complete with available versions
                    COMPREPLY=($(compgen -W "$(_list_installed_versions $cPlatform $pkgName)" -- "$compCWord"))
                fi
                ;;
        esac
    fi
}

complete -F _lpkgm_completions lpkgm-na64.sh
