#!/bin/bash

set -e

echo "Bootstrapping the docker host"
deployd init foo

echo "Now running: $*"
exec $*
