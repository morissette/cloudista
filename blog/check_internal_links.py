#!/usr/bin/env python3
"""
Identify missing internal links across cloudista.org blog posts.

For each defined link cluster (e.g. "terraform", "kubernetes"), every post in
the cluster should ideally link to every other post in the same cluster.  This
script fetches content_md from the DB and reports which of those cross-links
are absent.

Usage:
  POPULATE_DB_DSN="postgresql://..." python3 check_internal_links.py
  POPULATE_DB_DSN="postgresql://..." python3 check_internal_links.py --cluster terraform
  POPULATE_DB_DSN="postgresql://..." python3 check_internal_links.py --verbose
  POPULATE_DB_DSN="postgresql://..." python3 check_internal_links.py --dry-run
"""

import argparse
import logging
import os

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_DEFAULT_DSN = "postgresql://cloudista:cloudista_dev@localhost:5433/cloudista"
DB_DSN = os.environ.get("POPULATE_DB_DSN", _DEFAULT_DSN)
if DB_DSN == _DEFAULT_DSN:
    log.warning("Using default dev DSN — set POPULATE_DB_DSN for production")

# ---------------------------------------------------------------------------
# Link clusters
# Each cluster maps a topic name to the list of post slugs that belong to it.
# Every post in a cluster is expected to link to every other post in that
# cluster via an internal /blog/<slug> path.
# ---------------------------------------------------------------------------

CLUSTERS = {
    "terraform": [
        "terraform-getting-started",
        "terraform-modules",
        "terraform-remote-state",
        "terraform-workspaces",
        "terraform-multi-cloud-state-management",
        "terraform-auto-merge-noop-plans",
        "terraform-multi-stage-refactor",
        "terraform-azure-infrastructure",
        "terraform-gcp-getting-started",
    ],
    "kubernetes": [
        "kubectl-tips-and-tricks",
        "helm-basics",
        "deploying-to-kubernetes-before-helm",
        "kubernetes-rbac",
        "kubernetes-resource-limits",
        "writing-kubernetes-controllers-go",
        "kubernetes-admission-webhooks-go",
        "argo-cd-gitops",
        "argocd-applicationsets",
        "opa-rego-policy-as-code",
        "vault-agent-kubernetes",
        "chaos-engineering",
        "microservices-n-k8s",
        "slack-api-in-kubernetes-pre-helm",
        "kubernetes-operators",
    ],
    "security": [
        "vault-secrets-management",
        "vault-agent-kubernetes",
        "gcp-kms-vault-auto-unseal",
        "gcp-secret-manager-migration-from-vault",
        "aws-parameter-store",
        "lambda-environment-variables",
        "aws-kms-envelope-encryption-go",
        "key-rotation-automation-go",
        "hsm-key-management-production",
    ],
    "go": [
        "go-grpc-getting-started",
        "grpc-in-go",
        "grpc-mtls-golang",
        "opentelemetry-go",
        "opentelemetry-go-instrumentation",
        "go-context-patterns",
        "fips-140-2-golang",
        "opentelemetry-python-tracing",
        "writing-kubernetes-controllers-go",
        "kubernetes-admission-webhooks-go",
    ],
    "cicd": [
        "jenkins-declarative-pipelines",
        "jenkins-pipeline-multi-branch-strategy",
        "jenkins-shared-library-architecture",
        "jenkins-kubernetes-plugin",
        "github-actions-first-look",
        "github-actions-migrating-from-jenkins",
        "argo-cd-gitops",
        "argocd-applicationsets",
        "tekton-pipelines",
    ],
    "lambda": [
        "introduction-aws-lambda",
        "aws-lambda-api-gateway",
        "lambda-layers",
        "lambda-environment-variables",
        "scheduling-lambda-cloudwatch-events",
        "lambda-restart-ec2",
    ],
    "saltstack": [
        "saltstack-getting-started",
        "saltstack-pillars-and-grains",
        "saltstack-orchestration-reactor",
        "saltstack-production-lessons",
    ],
    "nfcu": [
        "nfcu-banking-api-reverse-engineering",
        "nfcu-auth-implementation",
    ],
}


def fetch_content(conn, slugs: list[str]) -> dict[str, str | None]:
    """Return {slug: content_md} for every slug in the list.

    Slugs not found in the DB are returned with None as the content so the
    caller can distinguish "post exists but is empty" from "post not in DB".
    """
    if not slugs:
        return {}

    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute(
        "SELECT slug, content_md FROM posts WHERE slug = ANY(%s)",
        (slugs,),
    )
    rows = cur.fetchall()

    content_map: dict[str, str | None] = {slug: None for slug in slugs}
    for row in rows:
        content_map[row["slug"]] = row["content_md"] or ""
    return content_map


def check_cluster(
    cluster_name: str,
    slugs: list[str],
    content_map: dict[str, str | None],
    verbose: bool,
) -> tuple[int, int]:
    """Check cross-links within one cluster.

    Returns (present_count, total_possible) where total_possible is the number
    of ordered pairs (from, to) with from != to whose source post exists in the
    DB.
    """
    present = 0
    possible = 0

    for from_slug in slugs:
        content = content_map.get(from_slug)
        if content is None:
            # Post not in DB — skip but note it
            log.warning("  [%s] slug not in DB: %s", cluster_name, from_slug)
            continue

        for to_slug in slugs:
            if from_slug == to_slug:
                continue

            possible += 1
            link_target = f"/blog/{to_slug}"
            found = link_target in content

            if found:
                present += 1
                if verbose:
                    print(f"OK       {cluster_name:<12}  {from_slug}  ->  {to_slug}")
            else:
                print(f"MISSING  {cluster_name:<12}  {from_slug}  ->  {to_slug}")

    return present, possible


def run(conn, cluster_filter: str | None, verbose: bool) -> None:
    """Main logic: iterate clusters, fetch content, report results."""
    clusters_to_check = (
        {cluster_filter: CLUSTERS[cluster_filter]}
        if cluster_filter
        else CLUSTERS
    )

    # Collect all unique slugs we need to fetch in one query
    all_slugs: list[str] = list(
        {slug for slugs in clusters_to_check.values() for slug in slugs}
    )
    log.info("Fetching content for %d unique slugs...", len(all_slugs))
    content_map = fetch_content(conn, all_slugs)

    grand_present = 0
    grand_possible = 0

    for cluster_name, slugs in clusters_to_check.items():
        log.info("Checking cluster: %s (%d posts)", cluster_name, len(slugs))
        present, possible = check_cluster(cluster_name, slugs, content_map, verbose)
        grand_present += present
        grand_possible += possible

        # Per-cluster summary
        missing = possible - present
        pct = (present / possible * 100) if possible else 0
        print(
            f"  SUMMARY  {cluster_name:<12}  "
            f"{present}/{possible} links present  "
            f"({missing} missing, {pct:.0f}%)"
        )
        print()

    # Grand total
    total_missing = grand_possible - grand_present
    total_pct = (grand_present / grand_possible * 100) if grand_possible else 0
    print("=" * 70)
    print(
        f"TOTAL  {grand_present}/{grand_possible} links present  "
        f"({total_missing} missing, {total_pct:.0f}%)"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Report missing internal cross-links between cloudista.org posts"
    )
    parser.add_argument(
        "--cluster",
        choices=list(CLUSTERS.keys()),
        help="Limit check to a single cluster",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Also print OK lines for links that are already present",
    )
    # --dry-run is a no-op alias (the script never writes anything) but it is
    # provided so callers can pass it for consistency with other blog scripts.
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No-op alias — this script is always read-only",
    )
    args = parser.parse_args()

    if args.dry_run:
        log.info("--dry-run specified; script is already read-only, proceeding normally")

    conn = psycopg2.connect(DB_DSN)
    try:
        run(conn, cluster_filter=args.cluster, verbose=args.verbose)
    finally:
        conn.close()

    log.info("Done.")


if __name__ == "__main__":
    main()
