#!/usr/bin/env sh

# Make sure consul runs via upstart.
# This is for single-host deployments, using the upstart
# and registrator plugins.

set -e

UPSTART_DIR="/etc/init"


if [ -n "$1" ]; then
    echo "Resolving $1 to a ip address"
    # http://unix.stackexchange.com/a/20823/20509
    ip=$(resolveip -s $1)
else
    ip=$(ifconfig | grep -A 1 'docker0' | tail -1 | cut -d ':' -f 2 | cut -d ' ' -f 1)
fi

if [ ! -n "ip" ]; then
    echo "Did not find host IP to use"
    exit 1
fi


# Run consul on boot, or when the control root service starts.
cat > $UPSTART_DIR/consul.conf <<EOF
description "consul"
start on (filesystem and started docker)
stop on runlevel [!2345] or stopping docker
respawn
script
  # It would appear "started docker" does not mean docker is
  # actually ready, so wait first until it is.
  FILE=/var/run/docker.sock
  while [ ! -e $FILE ] ; do
    inotifywait -t 2 -e create \$(dirname $FILE)
  done
  sleep 1

  docker rm -f consul || true
  mkdir -p /srv/consul
  docker run --rm --name consul -v /srv/consul:/data -p $ip:8400:8400 -p $ip:8500:8500 -p $ip:53:53/udp -h $(hostname) progrium/consul -server -bootstrap -ui-dir /ui -advertise $ip
end script
EOF

# Run ambassadord
cat > $UPSTART_DIR/ambassadord.conf <<EOF
description "ambassadord"
start on (filesystem and started docker)
stop on runlevel [!2345] or stopping docker
respawn
script
  # It would appear "started docker" does not mean docker is
  # actually ready, so wait first until it is.
  FILE=/var/run/docker.sock
  while [ ! -e $FILE ] ; do
    inotifywait -t 2 -e create \$(dirname $FILE)
  done
  sleep 1

  RUNNING=$(docker inspect --format="{{ .State.Running }}" $CONTAINER 2> /dev/null)
  if [ $? -eq 1 ]; then
     docker run --rm -v /var/run/docker.sock:/var/run/docker.sock --name backends --dns $ip  progrium/ambassadord --omnimode
  else
     docker start -a backends
  fi
end script

post-start script
  docker run --rm --privileged --net container:backends progrium/ambassadord --setup-iptables
end script
EOF

# Run registrator
cat > $UPSTART_DIR/registrator.conf <<EOF
description "registrator"
start on (filesystem and started docker)
stop on runlevel [!2345] or stopping docker
respawn
script
  # It would appear "started docker" does not mean docker is
  # actually ready, so wait first until it is.
  FILE=/var/run/docker.sock
  while [ ! -e $FILE ] ; do
    inotifywait -t 2 -e create \$(dirname $FILE)
  done
  sleep 1

  docker rm -f registrator || true
  docker run -v /var/run/docker.sock:/tmp/docker.sock -h $(hostname) --name registrator gliderlabs/registrator -ip $ip consul://$ip:8500 -resync 60
end script
EOF

# Run

# The upstart plugin will hook services to start on "docker-deploy".
cat >  $UPSTART_DIR/docker-deploy.conf <<EOF
description "docker-deploy root"
EOF

# Disable docker attempting to restart containers
#sudo sh -c "echo 'DOCKER_OPTS=\"-r=false --dns 172.17.42.1 --dns 8.8.8.8 --dns-search service.consul\"' > /etc/default/docker"
#initctl stop docker
#initctl start docker

