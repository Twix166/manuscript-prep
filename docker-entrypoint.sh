#!/bin/sh
set -eu

mkdir -p /app/runtime_data/runtime /app/runtime_data/uploads
chown -R manuscriptprep:manuscriptprep /app/runtime_data

cmd=""
for arg in "$@"; do
  cmd="$cmd '$arg'"
done

exec su -s /bin/sh manuscriptprep -c "exec$cmd"
