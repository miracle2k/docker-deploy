#!/bin/sh

# Common utilities used by all shell scripts. Source this file.


if [ ! -n "$RECEIVE_DEBUG" ]; then
    export RECEIVE_DEBUG=/dev/null
fi


echo "$0 called with $*" >> $RECEIVE_DEBUG


# Give caller an httpie auth header to use.
export AUTH="Authorization:$CONTROLLER_AUTH_KEY"



function get_controller_ip() {
    controller=$(sdutil services docker-deploy 2>&1)
    exitcode=$?
    if (($exitcode > 0));  then
        echo "Controller discovery failed with $exitcode and output: $controller" >> $RECEIVE_DEBUG
        exit 1
    fi
    echo "Controller runs at: $controller" > $RECEIVE_DEBUG
    echo $controller
}


function http_request() {
    result=$(http --ignore-stdin --check-status --follow "$@" 2>&1)
    exitcode=$?
    if (($exitcode > 0));  then
        echo "HTTP query failed with exit code $exitcode and output: $result" >> $RECEIVE_DEBUG
        exit 1
    fi
    echo "Result is: $result" >> $RECEIVE_DEBUG
    echo $result
}
