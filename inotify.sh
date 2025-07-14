#!/usr/bin/env bash

while true; do
  FILE_PATH=$(inotifywait -e close_write -r --format '%w%f' --includei '\.txt$' .)
  echo "$(date '+%Y-%m-%d %H:%M:%S') File changed: ${FILE_PATH}"
  ./chathistory.py "$FILE_PATH"
done
