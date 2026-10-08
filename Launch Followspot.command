#!/bin/zsh
# Select a Python that includes Tk; this does not install or change anything.
set -u
cd -- "$(dirname -- "$0")" || exit 1
for followspot_python in \
  "$PWD/.venv/bin/python" \
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  /opt/homebrew/bin/python3 \
  /usr/local/bin/python3 \
  /usr/bin/python3; do
  if [[ -x "$followspot_python" ]] && "$followspot_python" -c 'import tkinter, _tkinter' >/dev/null 2>&1; then
    "$followspot_python" "$PWD/followspot.py" "$@"
    followspot_result=$?
    if (( followspot_result != 0 )); then
      print 'Followspot exited with an error. See the message above and README.md.'
      read 'followspot_ack?Press Return to close. '
    fi
    exit "$followspot_result"
  fi
done
print 'No Python with Tk support was found.'
print 'Install Python from python.org, or install matching Homebrew python-tk.'
read 'followspot_ack?Press Return to close. '
exit 1
