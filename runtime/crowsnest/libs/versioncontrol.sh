#!/bin/bash

#### version control library

#### crowsnest - A webcam Service for multiple Cams and Stream Services.
####
#### Written by Stephan Wendel aka KwadFan <me@stephanwe.de>
#### Copyright 2021
#### https://github.com/mainsail-crew/crowsnest
####
#### This File is distributed under GPLv3
####
#### Description: Checks Versions of Streamer and ffmpeg
####

# shellcheck enable=require-variable-braces

# Exit upon Errors
set -Ee

function versioncontrol {

    function vc_log_msg {
        log_msg "Version Control: ${1}"
    }

    function get_ustreamer_version {
        local cur_ver
        cur_ver="v$("${BASE_CN_PATH}"/bin/ustreamer/ustreamer -v)"
        vc_log_msg "ustreamer version: ${cur_ver}"
    }


    function get_ffmpeg_version {
        local cur_ver avail_ver
            avail_ver="$(dpkg-query -W ffmpeg | awk -F':' '{print $2}')"
            cur_ver="$(ffmpeg -version | awk 'NR==1 {print $3}')"
            if [[ "${cur_ver}" == "${avail_ver}" ]]; then
                vc_log_msg "ffmpeg is up to date. (${cur_ver})"
            fi
            if [[ "${cur_ver}" != "${avail_ver}" ]]; then
                vc_log_msg "ffmpeg new version available: ${avail_ver} (${cur_ver})."
            fi
    }

    ### MAIN
    function main {
        if [[ "${CROWSNEST_LOG_LEVEL}" != "quiet" ]]; then
            get_ustreamer_version
            get_ffmpeg_version
        fi
    }

    main
    return
}
