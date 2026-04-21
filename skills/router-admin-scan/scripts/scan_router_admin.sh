#!/usr/bin/env bash
set -euo pipefail

PORTS="80,443,8080,8443,10000,5000,5001"
IFACE=""
SUBNET=""
TIMEOUT=3
LIMIT=0

usage() {
  cat <<'EOF'
Usage: scan_router_admin.sh [--iface IFACE] [--subnet CIDR] [--ports LIST] [--timeout SEC] [--limit N]

Locate likely router/AP admin pages on the current local subnet using a limited port scan.

Options:
  --iface IFACE    Network interface to inspect. Defaults to the default-route interface.
  --subnet CIDR    Subnet to scan. Defaults to the directly-connected IPv4 subnet on the interface.
  --ports LIST     Comma-separated ports to scan. Default: 80,443,8080,8443,10000,5000,5001
  --timeout SEC    Curl timeout per probe. Default: 3
  --limit N        Max candidate hosts to probe after nmap. Default: 0 (no limit)
  -h, --help       Show this help.
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

detect_iface() {
  ip route show default | awk '/default/ {print $5; exit}'
}

detect_subnet() {
  local iface=$1
  ip route show dev "$iface" proto kernel scope link \
    | awk '$1 ~ /^[0-9]/ && $1 !~ /^169\.254\./ {print $1; exit}'
}

extract_title() {
  tr '\n' ' ' \
    | sed -n 's:.*<title[^>]*>\(.*\)</title>.*:\1:p' \
    | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//' \
    | cut -c1-120
}

brand_from_text() {
  local text=$1
  if grep -qiE '小米路由器|miwifi|xiaoqiang' <<<"$text"; then
    echo "Xiaomi"
  elif grep -qiE 'tp-?link|tplink|tl-' <<<"$text"; then
    echo "TP-Link"
  elif grep -qiE 'openwrt|luci' <<<"$text"; then
    echo "OpenWrt/LuCI"
  elif grep -qiE 'h3c|新华三' <<<"$text"; then
    echo "H3C"
  elif grep -qiE 'huawei|华为' <<<"$text"; then
    echo "Huawei"
  elif grep -qiE 'ruijie|锐捷' <<<"$text"; then
    echo "Ruijie"
  elif grep -qiE 'tenda|腾达' <<<"$text"; then
    echo "Tenda"
  elif grep -qiE 'mercury|水星' <<<"$text"; then
    echo "Mercury"
  elif grep -qiE 'zte|中兴' <<<"$text"; then
    echo "ZTE"
  else
    echo "Unknown"
  fi
}

score_candidate() {
  local text=$1
  local score=10
  if grep -qiE '小米路由器|miwifi|xiaoqiang|tp-?link|tplink|openwrt|luci|h3c|新华三|华为|ruijie|锐捷|tenda|腾达|mercury|水星|router|wireless|login' <<<"$text"; then
    score=$((score + 50))
  fi
  if grep -qiE '/cgi-bin/luci/web|/cgi-bin/luci' <<<"$text"; then
    score=$((score + 30))
  fi
  if grep -qiE 'camera|nvr|printer|laserjet|hp |seetong|aten|hikvision|dahua|canon|epson' <<<"$text"; then
    score=$((score - 40))
  fi
  printf '%d' "$score"
}

probe_url() {
  local url=$1
  local headers body title server location
  headers=$(curl -m "$TIMEOUT" -skI "$url" 2>/dev/null | tr -d '\r' || true)
  body=$(curl -m "$TIMEOUT" -skL "$url" 2>/dev/null | tr -d '\000' | head -c 4096 || true)
  title=$(printf '%s' "$body" | extract_title)
  server=$(printf '%s\n' "$headers" | awk -F': ' 'tolower($1)=="server"{print $2; exit}')
  location=$(printf '%s\n' "$headers" | awk -F': ' 'tolower($1)=="location"{print $2; exit}')
  printf '%s\t%s\t%s' "$title" "$server" "$location"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --iface)
      IFACE=${2:-}
      shift 2
      ;;
    --subnet)
      SUBNET=${2:-}
      shift 2
      ;;
    --ports)
      PORTS=${2:-}
      shift 2
      ;;
    --timeout)
      TIMEOUT=${2:-}
      shift 2
      ;;
    --limit)
      LIMIT=${2:-}
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_cmd ip
require_cmd nmap
require_cmd curl

IFACE=${IFACE:-$(detect_iface)}
if [[ -z "$IFACE" ]]; then
  echo "Could not determine default interface." >&2
  exit 1
fi

SUBNET=${SUBNET:-$(detect_subnet "$IFACE")}
if [[ -z "$SUBNET" ]]; then
  echo "Could not determine a directly-connected IPv4 subnet for interface $IFACE." >&2
  exit 1
fi

echo "Interface: $IFACE"
echo "Subnet:    $SUBNET"
echo "Ports:     $PORTS"
echo

tmp_scan=$(mktemp)
tmp_rows=$(mktemp)
trap 'rm -f "$tmp_scan" "$tmp_rows"' EXIT

nmap -n -Pn -p "$PORTS" --open -oG "$tmp_scan" "$SUBNET" >/dev/null

if [[ "$LIMIT" =~ ^[0-9]+$ ]] && [[ "$LIMIT" -gt 0 ]]; then
  mapfile -t lines < <(grep '/open/' "$tmp_scan" | head -n "$LIMIT")
else
  mapfile -t lines < <(grep '/open/' "$tmp_scan")
fi

if [[ ${#lines[@]} -eq 0 ]]; then
  echo "No hosts with open candidate admin ports were found."
  exit 0
fi

for line in "${lines[@]}"; do
  ip_addr=$(awk '{print $2}' <<<"$line")
  ports_field=${line#*Ports: }
  open_ports=$(printf '%s' "$ports_field" \
    | sed 's/, /\n/g' \
    | awk -F/ '$2=="open"{print $1}' \
    | paste -sd, -)

  best_score=-999
  best_brand="Unknown"
  best_port=""
  best_scheme=""
  best_title=""
  best_server=""
  best_location=""

  IFS=',' read -r -a port_array <<<"$open_ports"
  for port in "${port_array[@]}"; do
    case "$port" in
      443|8443|5001)
        scheme="https"
        ;;
      *)
        scheme="http"
        ;;
    esac

    url="${scheme}://${ip_addr}:${port}"
    if [[ "$port" == "80" || "$port" == "443" ]]; then
      url="${scheme}://${ip_addr}"
    fi

    result=$(probe_url "$url")
    title=$(cut -f1 <<<"$result")
    server=$(cut -f2 <<<"$result")
    location=$(cut -f3 <<<"$result")
    fingerprint="${title} ${server} ${location} ${url}"
    brand=$(brand_from_text "$fingerprint")
    score=$(score_candidate "$fingerprint")

    if [[ "$score" -gt "$best_score" ]]; then
      best_score=$score
      best_brand=$brand
      best_port=$port
      best_scheme=$scheme
      best_title=$title
      best_server=$server
      best_location=$location
    fi
  done

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$best_score" \
    "$ip_addr" \
    "$open_ports" \
    "$best_brand" \
    "$best_scheme" \
    "$best_port" \
    "$best_server" \
    "$best_title ${best_location}" >>"$tmp_rows"
done

printf '%-6s %-15s %-18s %-14s %-10s %-20s %s\n' "score" "ip" "ports" "brand" "best" "server" "title/location"
sort -t $'\t' -k1,1nr -k2,2 "$tmp_rows" \
  | while IFS=$'\t' read -r score ip_addr ports brand scheme port server summary; do
      best="${scheme}:${port}"
      printf '%-6s %-15s %-18s %-14s %-10s %-20s %s\n' \
        "$score" "$ip_addr" "$ports" "$brand" "$best" "${server:--}" "${summary:--}"
    done
