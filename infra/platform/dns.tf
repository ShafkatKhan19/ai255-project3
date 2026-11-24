# The public address of the HTTPS load balancer and the name that points
# at it. The load balancer itself is created by GKE from k8s/https.yaml,
# which asks for this address by name.

resource "google_compute_global_address" "snip" {
  name = "${var.name}-ip"
}

# The zone was created in Project 1 and is shared with it, so it is only
# looked up here, never managed. A teardown removes the one record below
# and leaves the zone alone.
data "google_dns_managed_zone" "zone" {
  name = var.dns_zone
}

resource "google_dns_record_set" "site" {
  managed_zone = data.google_dns_managed_zone.zone.name
  name         = "${var.domain}."
  type         = "A"
  ttl          = 300
  rrdatas      = [google_compute_global_address.snip.address]
}
