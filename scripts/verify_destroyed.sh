#!/usr/bin/env bash
# After a teardown, look for anything of Snip's that still exists.
#
#   bash scripts/verify_destroyed.sh PROJECT_ID DNS_ZONE DOMAIN
#
# Terraform only removes what it created. The load balancers, firewall
# rules and endpoint groups are created by GKE, so this is the check that
# they went too. Exit code 0 means nothing was found.
#
# Project 1 lives in the same Google Cloud project. Its resources have
# other names (web-vm, web-vpc, web-ip, ...) and are not matched here.
set -u
project="$1"; zone="$2"; domain="$3"
found=0

check() {
  local what="$1"; shift
  local out
  # Only what the command prints as its result counts. gcloud also writes
  # warnings ("filter keys were not present in any resource" when a list is
  # empty), and those must not be mistaken for a leftover resource.
  if ! out=$("$@" 2>"$errors"); then
    echo "ERROR  $what: $(tr '\n' ' ' < "$errors")"
    found=1
  elif [ -n "$out" ]; then
    echo "LEFT   $what: $(echo "$out" | tr '\n' ' ')"
    found=1
  else
    echo "gone   $what"
  fi
}
errors=$(mktemp)

g() { gcloud --project "$project" "$@"; }
# Project 1 is one VM with its own address: it has no load balancer, so
# any load balancer part found in the project belongs to Snip. Firewall
# rules and disks are matched by network and name, because Project 1 has
# those too.

echo '```'
check "GKE cluster"              g container clusters list --filter='name=snip' --format='value(name)'
check "Firestore database"       g firestore databases list --format='value(name)'
check "image repository"         g artifacts repositories list --filter='name~/snip$' --format='value(name)'
check "network"                  g compute networks list --filter='name=snip' --format='value(name)'
check "subnet"                   g compute networks subnets list --filter='name=snip' --format='value(name)'
check "reserved address"         g compute addresses list --filter='name=snip-ip' --format='value(name)'
check "DNS record"               g dns record-sets list --zone "$zone" --name "$domain." --type A --format='value(name)'
check "node service account"     g iam service-accounts list --filter='email~^snip-nodes@' --format='value(email)'
check "forwarding rules"         g compute forwarding-rules list --format='value(name)'
check "target HTTP proxies"      g compute target-http-proxies list --format='value(name)'
check "target HTTPS proxies"     g compute target-https-proxies list --format='value(name)'
check "URL maps"                 g compute url-maps list --format='value(name)'
check "backend services"         g compute backend-services list --format='value(name)'
check "target pools"             g compute target-pools list --format='value(name)'
check "health checks"            g compute health-checks list --format='value(name)'
check "endpoint groups"          g compute network-endpoint-groups list --format='value(name)'
check "certificates"             g compute ssl-certificates list --format='value(name)'
check "firewall rules"           g compute firewall-rules list --filter='network~/snip$' --format='value(name)'
check "disks"                    g compute disks list --filter='name~^(gke-snip|pvc-)' --format='value(name)'
check "IAM: Firestore binding"   g projects get-iam-policy "$project" --flatten='bindings[].members' --filter='bindings.members~sa/snip-data' --format='value(bindings.role)'
check "IAM: node binding"        g projects get-iam-policy "$project" --flatten='bindings[].members' --filter='bindings.members~snip-nodes@' --format='value(bindings.role)'
echo '```'

if [ "$found" -eq 0 ]; then
  echo "Nothing left. The environment is gone."
else
  echo "Something is left (see LEFT / ERROR lines above)."
fi
exit "$found"
