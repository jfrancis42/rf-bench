#!/bin/bash
#
# Post comment to PR #5 on philpagel/ET54.py
#

GITHUB_TOKEN=$(cat ~/Dropbox/build/creds/github.txt | tail -1)

curl -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/philpagel/ET54.py/issues/5/comments \
  -d '{"body":"Fixed. Now back to depending on your ET54.py instead of my updated version."}'

echo ""
echo "Comment posted to https://github.com/philpagel/ET54.py/pull/5"
