# Snip: Infrastructure as Code and CI/CD

**AI 255 Project 3.** Shafkat Khalek Khan (100818151). Prof. Yair Chaya, Fall 2026.

**Repository:** https://github.com/ShafkatKhan19/ai255-project3
**Live endpoint:** https://snip.cloud.gadgetgroveny.com
**Provider:** Google Cloud, region us-central1.

> DRAFT. Sections 7 and 8 report measurements. They say NOT CAPTURED YET until the real teardown and rebuild have been run, and nothing in them is estimated.

## 1. Summary

Project 2 was a link shortener made of three services (`web`, `links`, `stats`) on GKE Autopilot with Firestore. It worked, but it was built by a PowerShell script I ran on my PC: about twenty `gcloud` and `kubectl` commands in a fixed order. Project 3 replaces that script. The environment is now described in files, and a pipeline applies them.

| Requirement | How it is met |
|---|---|
| Reproduce the entire Project 2 environment from version-controlled infrastructure code | `infra/platform` (Terraform, 11 resources) creates the network, cluster, image repository, Firestore database, IAM, reserved address and DNS record. `k8s/` (Kustomize, 22 objects) creates everything inside the cluster. |
| A pipeline that builds, tests and deploys automatically on commit | `.github/workflows/deploy.yml` runs on every push to `main`: checks, `terraform apply`, image build and push, rollout, live test. |
| Destroyable and rebuildable from scratch | `.github/workflows/destroy.yml` removes everything and then proves nothing is left. Running `deploy` again rebuilds it. |
| Demonstration is a full teardown and rebuild | `scripts/demo.ps1` runs both workflows and times them. Results in Section 7. |

## 2. What is code now

![Pipeline](pipeline.png)

| Layer | Tool | Where | Who applies it |
|---|---|---|---|
| Pipeline identity, state bucket, APIs | Terraform | `infra/bootstrap` | A person, once |
| Network, cluster, registry, Firestore, IAM, address, DNS | Terraform | `infra/platform` | Pipeline |
| Container images | Dockerfiles | `services/*` | Pipeline |
| Deployments, Services, autoscalers, NetworkPolicy, HTTPS Ingress, certificate | Kubernetes manifests + Kustomize | `k8s/` | Pipeline |

Two things are different from Project 2 on purpose:

- **Its own network.** Project 2 used the project's `default` network. Project 3 creates a VPC and a subnet for the cluster, so a teardown removes every trace and a leftover firewall rule or load balancer shows up as a failed delete, not as a silent charge.
- **Its own node account.** Project 2's nodes ran as the default Compute Engine service account. Project 3 creates `snip-nodes` with the minimal node role and read access to one image repository.

One small change to the application: `web` reports the commit it was built from at `/api/whoami`, so the pipeline can check that the pods serving traffic are the ones it just built.

## 3. Moving from the hand-built environment

The Project 2 environment already existed under the same names. Terraform will not take over a resource it did not create unless it is imported. I chose to delete the hand-built environment (`scripts/retire_project2.ps1`) and let the pipeline create everything, for two reasons: the cluster had to be replaced anyway because it moves to a new network, and after the deletion I can say that every resource in the environment was created by the pipeline.

NOT CAPTURED YET: date and output of the retirement run.

## 4. Terraform design

**Two folders, not one.** `infra/bootstrap` holds what the pipeline needs before it can run: the bucket for its state and the identity it signs in with. The pipeline cannot create these itself. Everything else is in `infra/platform`, and that is the part that is destroyed and rebuilt.

**Kubernetes objects are not in Terraform.** Terraform has a Kubernetes provider, and I considered putting the Deployments in it so one `terraform destroy` would remove everything. I did not, because the provider needs a cluster to exist while it plans, which does not work in the same run that creates the cluster. The manifests are still version-controlled and applied by the pipeline with `kubectl apply -k`. The cost of this choice is in Section 6: the teardown has to delete the namespace before it runs `terraform destroy`.

**State.** The state is in a Cloud Storage bucket with versioning on. The backend locks it during a run, and the workflows share one concurrency group, so two applies cannot overlap.

**The Firestore wait.** Google does not allow a database ID to be reused until five minutes after it was deleted, and the services use the `(default)` database. A rebuild started right after a teardown would fail there. The database resource has `depends_on` the cluster. That is not a real dependency: it only makes Terraform create the database after the cluster, which takes longer than five minutes.

**Tests.** `infra/platform/tests/plan.tftest.hcl` runs `terraform test` with a mock provider, so it needs no credentials. It checks the decisions this report depends on: the cluster and database can be destroyed, the Firestore role goes to one Kubernetes service account in one namespace, and a domain with a trailing dot is rejected.

## 5. The pipeline

| Stage | Steps |
|---|---|
| checks | 37 unit tests. `terraform fmt -check`, `validate` for both folders, `terraform test`. Manifests rendered with Kustomize, checked against the Kubernetes schemas, and checked by `scripts/check_manifests.py` for the Project 2 requirements (both probes, autoscaler with at least 2 pods, non-root, internal services stay internal). The three images are built and run together with the Firestore emulator, and the end-to-end test runs against them. |
| infrastructure | `terraform plan -out`, then `apply` of that saved plan. |
| images | Three parallel builds, tagged with the commit SHA, pushed to Artifact Registry. |
| rollout | Write the project ID and domain into `params.env`, set the three image tags, `kubectl apply -k k8s`, wait for each Deployment, run the end-to-end test against the live address, check every pod reports this commit. On failure, `kubectl rollout undo`. |

**No keys.** The repository has no secrets. GitHub Actions gets a short-lived token from GitHub, and Google exchanges it for credentials of the `snip-deployer` service account (Workload Identity Federation). The exchange is only allowed for this repository on the `main` branch, so a pull request or a fork gets nothing.

**Tags are commits.** Images are never tagged `latest`. Any running pod can be traced to the commit that built it.

**Parking.** After a teardown the destroy workflow leaves a marker in the state bucket. While it is there, a push runs the checks and stops. Running `deploy` by hand removes the marker and rebuilds.

## 6. Teardown

The order matters. The load balancers are created by GKE on behalf of the `web` Service and the Ingress, so they are not in Terraform's state. If the cluster were destroyed first, they would be orphaned: still billed, and holding the network so it could not be deleted. The destroy workflow therefore:

1. deletes the `snip` namespace and waits, which makes GKE remove the load balancers;
2. runs `terraform destroy`;
3. runs `scripts/verify_destroyed.sh`, which lists 21 kinds of resource and fails if any of Snip's remain.

What survives a teardown: the bootstrap (state bucket, pipeline identity), the enabled APIs, and the Project 1 resources that share the Google Cloud project, including the DNS zone.

## 7. Demonstration: teardown and rebuild

NOT CAPTURED YET. This section will hold, from `evidence/`:

- the teardown run: time per step and the output of `verify_destroyed.sh`;
- the rebuild run: time per stage;
- the end-to-end test against the rebuilt site, over HTTP and then HTTPS;
- how long the new certificate took.

## 8. What did not work

NOT CAPTURED YET. Written after the live runs, from what actually failed.

## 9. Limits and what I would change

- **The bootstrap state is on my PC.** `infra/bootstrap` uses local state because the bucket it would use does not exist until it has run. It is seven resources applied once, and they can be imported if the file is lost, but it is not shared or locked.
- **The pipeline's identity is powerful.** It can create and delete clusters, networks and service accounts in the project, and it has DNS admin for the whole project, which includes Project 1's zone. I limited what I could: it can only be used from `main` of one repository, and its permission to change project IAM is restricted by a condition to two roles. A stricter setup would give it a project of its own.
- **Commits deploy with no approval step.** That is what the assignment asks for. For a real system I would add a required reviewer on the GitHub environment before `apply`.
- **A teardown deletes the data.** Correct for this project. With data worth keeping, the database would move to the bootstrap layer and have delete protection on.
- **HTTPS is not instant after a rebuild.** Google issues a new certificate each time. The pipeline tests over HTTP on the load balancer address and reports the certificate status.
- **The cluster is not private.** Nodes have public addresses, as in Project 2. Private nodes would need Cloud NAT, which adds a fixed cost.

## 10. AI use

DRAFT, to be edited by me so that it is true.

I used Claude (Anthropic) throughout this project. Claude wrote the Terraform, the workflows, the Kustomize changes, the scripts, the tests and this report, working from the Project 3 description in the syllabus and from my Project 2 repository. Claude also ran the validation on my PC. Commits that contain AI-written code carry a `Co-Authored-By: Claude` line.

My own part: NOT WRITTEN YET.
