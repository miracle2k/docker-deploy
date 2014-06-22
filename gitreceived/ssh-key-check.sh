#!/bin/bash

source /bin/utils.sh


controller=$(get_controller_ip) || exit 1
result=$(http_request GET http://$controller/gitreceive/check-key "user==$1" "key==$2") || exit 1
[ "$result" == "ok" ] && exit 0 || exit 1
