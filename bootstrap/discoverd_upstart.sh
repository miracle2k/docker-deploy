#!/usr/bin/env sh

# Make sure etcd and discoverd run via upstart.
# This is for single-host deployments, using the upstart
# and etcd_discoverd plugins.

set -e

#UPSTART_DIR="/etc/init"
UPSTART_DIR="./upstart"


if [ -n "$1" ]; then
    echo "Resolving $1 to a ip address"
    # http://unix.stackexchange.com/a/20823/20509
    ip=$(resolveip -s $1)
else
    # This will only work on OSX
    ip=$(ifconfig | grep -A 1 'en0' | tail -1 | cut -d ' ' -f 2)
fi


# Run etcd on boot, or when the control root service starts.
cat > $UPSTART_DIR/etcd.conf <<EOF
description "etcd"
start on (filesystem and started docker)
stop on runlevel [!2345]
respawn
script
  # It would appear "started docker" does not mean docker is
  # actually ready, so wait first until it is.
  FILE=/var/run/docker.sock
  while [ ! -e $FILE ] ; do
    inotifywait -t 2 -e create \$(dirname $FILE)
  done
  sleep 1
  docker run --rm --name -p 4001:4001 -p 7001:7001 etcd coreos/etcd -name local -data-dir /srv/etcd -bind-addr=0.0.0.0:4001 --peer-addr=$ip:7001
end script
EOF

cat >  $UPSTART_DIR/discoverd.conf <<EOF
description "discoverd"
start on started etcd
stop on stopping etcd
respawn
script
    docker run --rm --name discoverd -p 1111:1111 -e EXTERNAL_IP=$ip flynn/discoverd -etcd http://$ip:4001
end script
EOF

# The upstart plugin will hook services to start on "docker-deploy".
cat >  $UPSTART_DIR/docker-deploy.conf <<EOF
description "docker-deploy root"
start on started discoverd
stop on stopping discoverd
EOF
