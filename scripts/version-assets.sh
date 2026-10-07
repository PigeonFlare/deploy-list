#!/bin/sh
# Tag stylesheet and script links with the commit so each deploy shows up on the next
# page load even where browsers cache assets. Used by GitHub Actions and Cloudflare Pages.
set -eu
python3 -B scripts/build_seo.py
VERSION=$(printf %.8s "${1:?usage: version-assets.sh <commit-sha>}")
find site -name '*.html' -exec sed -i -E "s#(assets/[a-z]+\.(css|js))\"#\1?v=${VERSION}\"#g" {} +
grep -rho 'assets/[a-z]*\.[a-z]*?v=[0-9a-f]*' site --include='*.html' | sort | uniq -c
