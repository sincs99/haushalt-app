#!/bin/sh
# Wird vom nginx-Image beim Start ausgeführt (/docker-entrypoint.d/).
#
# Erzeugt /etc/nginx/snippets/real-ip.conf aus TRUSTED_PROXY_CIDRS: nur von diesen
# Adressen (vorgeschalteter Proxy, z. B. Nginx Proxy Manager im Docker-Netz) wird
# X-Forwarded-For als echte Client-IP übernommen. Mehrere Bereiche mit Komma oder
# Leerzeichen trennen. Default: 172.16.0.0/12 (Docker-Standardpools 172.17–172.31).
# Passt der Bereich nicht, sehen Backend und Rate-Limit alle Clients als eine IP (CASA-57).
set -eu

cidrs="${TRUSTED_PROXY_CIDRS:-172.16.0.0/12}"
out=/etc/nginx/snippets/real-ip.conf
tmp="$out.tmp"
: > "$tmp"
for cidr in $(echo "$cidrs" | tr ',' ' '); do
    # Nur IP/CIDR-Zeichen — verhindert, dass die Variable beliebige nginx-Direktiven einschleust
    case "$cidr" in
        *[!0-9a-fA-F:./]*)
            echo "30-casa-real-ip: ungültiger Eintrag in TRUSTED_PROXY_CIDRS: '$cidr'" >&2
            exit 1
            ;;
    esac
    echo "set_real_ip_from $cidr;" >> "$tmp"
done
mv "$tmp" "$out"
echo "30-casa-real-ip: vertraue X-Forwarded-For von: $cidrs"
