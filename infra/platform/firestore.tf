# The managed datastore. links and stats each own one collection in it.

resource "google_firestore_database" "default" {
  # The services use the project's default database, as in Project 2.
  name        = "(default)"
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  # A teardown deletes the database and everything in it. That is what
  # "rebuild from scratch" means, and it is the reason this would be set
  # the other way round for a system with data worth keeping.
  delete_protection_state = "DELETE_PROTECTION_DISABLED"
  deletion_policy         = "DELETE"

  # Not a real dependency. Google does not allow a database ID to be used
  # again until five minutes after it was deleted. Creating the cluster
  # takes longer than that, so making the database wait for the cluster
  # means a rebuild started straight after a teardown does not fail here.
  depends_on = [google_container_cluster.snip]
}
