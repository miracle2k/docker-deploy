#!/usr/bin/env sh

# Simply run etcd and discoverd via docker.
# This is mostly for a local dev environment.

set -e

if [ -n "$1" ]; then
    echo "Resolving $1 to a ip address"
    # http://unix.stackexchange.com/a/20823/20509
    ip=$(resolveip -s $1)
else
    # This will only work on OSX
    ip=$(ifconfig | grep -A 1 'en0' | tail -1 | cut -d ' ' -f 2)
fi

echo "Using host ip: $ip"
echo ""

# Shutdown existing containers
docker rm -f etcd discoverd || true

# Run etcd first
# It seems due to the stange way etcdctl connects, we need to set --peer-addr
docker run -d -p 4001:4001 -p 7001:7001 --name etcd -v /tmp/etcd:/data.etcd coreos/etcd -name local -data-dir /data.etcd -bind-addr=0.0.0.0:4001 --peer-addr=$ip:7001

# Then run discoverd
docker run -d --name discoverd --link etcd:etcd -p 1111:1111 -e EXTERNAL_IP=$ip flynn/discoverd -etcd http://$ip:4001

echo "export ETCD=$ip:4001"
echo "export DISCOVERD=$ip:1111"

