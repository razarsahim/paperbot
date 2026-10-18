#!/bin/bash
# usage: dl.sh URL OUTDIR ; downloads with retries, records HTTP status
u="$1"; out="$2/$(basename "$u")"
[ -s "$out" ] && exit 0
for i in 1 2 3 4; do
  code=$(curl -s -m 900 -w '%{http_code}' -o "$out.part" "$u")
  if [ "$code" = "200" ]; then mv "$out.part" "$out"; echo "OK $u"; exit 0; fi
  if [ "$code" = "404" ]; then rm -f "$out.part"; echo "404 $u"; exit 0; fi
  sleep 5
done
rm -f "$out.part"; echo "FAIL $code $u"
