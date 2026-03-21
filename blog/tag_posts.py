#!/usr/bin/env python3
"""
Auto-tag and categorize blog posts based on slug/title keyword matching.
Safe to re-run — uses ON CONFLICT DO NOTHING throughout.

Usage:
    python3 tag_posts.py              # tag all posts (skips already-tagged unless --all)
    python3 tag_posts.py --all        # re-tag every published post (clears first)
    python3 tag_posts.py --dry-run    # show matches without writing to DB
"""
import sys

import psycopg2
import psycopg2.extras

DB_DSN = "postgresql://cloudista:cloudista_dev@localhost:5433/cloudista"

# ── Categories ────────────────────────────────────────────────────────────────
# (display name, slug, description)

CATEGORIES = [
    ("AWS",                        "aws",                  "Amazon Web Services tutorials and guides"),
    ("GCP",                        "gcp",                  "Google Cloud Platform tutorials and guides"),
    ("Azure",                      "azure",                "Microsoft Azure tutorials and guides"),
    ("Kubernetes",                 "kubernetes",           "Container orchestration with Kubernetes"),
    ("Go / Golang",                "golang",               "Go programming language"),
    ("Python",                     "python",               "Python programming and scripting"),
    ("Terraform",                  "terraform",            "Infrastructure as Code with Terraform"),
    ("Docker",                     "docker",               "Containers and Docker"),
    ("Security & Encryption",      "security",             "Security, encryption, and key management"),
    ("Monitoring & Observability", "monitoring",           "Monitoring, logging, and observability"),
    ("Platform Engineering",       "platform-engineering", "Platform engineering and DevOps culture"),
    ("ChatOps",                    "chatops",              "ChatOps and team communication tooling"),
    ("Databases",                  "databases",            "Database design and operations"),
    ("Linux & Sysadmin",           "linux",                "Linux administration and systems"),
    ("CI/CD",                      "cicd",                 "Continuous integration and delivery"),
    ("Service Mesh",               "service-mesh",         "Service mesh, networking, and mTLS"),
    ("IBM Cloud",                  "ibm-cloud",            "IBM Cloud and enterprise platform engineering"),
    ("Serverless",                 "serverless",           "Serverless computing and FaaS"),
    ("Web",                        "web",                  "Web development, CMS, and frontend"),
    ("SaltStack",                  "saltstack",            "Configuration management with SaltStack"),
    ("Ansible",                    "ansible",              "Automation with Ansible"),
]

# ── Tags ─────────────────────────────────────────────────────────────────────
# (display name, slug) — more granular than categories

TAGS = [
    ("AWS",          "aws"),          ("EC2",         "ec2"),
    ("S3",           "s3"),           ("Lambda",      "lambda"),
    ("GCP",          "gcp"),          ("GKE",         "gke"),
    ("Azure",        "azure"),        ("AKS",         "aks"),
    ("Kubernetes",   "kubernetes"),   ("Helm",        "helm"),
    ("Terraform",    "terraform"),    ("Docker",      "docker"),
    ("Python",       "python"),       ("JavaScript",  "javascript"),
    ("Bash",         "bash"),         ("Linux",       "linux"),
    ("Nginx",        "nginx"),        ("Security",    "security"),
    ("IAM",          "iam"),          ("CI/CD",       "cicd"),
    ("Monitoring",   "monitoring"),   ("Prometheus",  "prometheus"),
    ("Grafana",      "grafana"),      ("Database",    "database"),
    ("MySQL",        "mysql"),        ("PostgreSQL",  "postgresql"),
    ("Redis",        "redis"),        ("Serverless",  "serverless"),
    ("SaltStack",    "saltstack"),    ("Ansible",     "ansible"),
    ("Drupal",       "drupal"),       ("WordPress",   "wordpress"),
    ("PHP",          "php"),          ("Go",          "golang"),
    ("Service Mesh", "service-mesh"), ("IBM Cloud",   "ibm-cloud"),
    ("ChatOps",      "chatops"),      ("GitOps",      "gitops"),
]

# ── Keyword rules ─────────────────────────────────────────────────────────────
# keyword → {"cats": [category slugs], "tags": [tag slugs]}

RULES = {
    # AWS
    "aws":               {"cats": ["aws"],                           "tags": ["aws"]},
    "amazon":            {"cats": ["aws"],                           "tags": ["aws"]},
    "ec2":               {"cats": ["aws", "linux"],                  "tags": ["ec2", "aws"]},
    "s3":                {"cats": ["aws"],                           "tags": ["s3", "aws"]},
    "lambda":            {"cats": ["aws", "serverless"],             "tags": ["lambda", "aws", "serverless"]},
    "elasticbeanstalk":  {"cats": ["aws"],                           "tags": ["aws"]},
    "ecs":               {"cats": ["aws", "docker"],                 "tags": ["aws", "docker"]},
    "eks":               {"cats": ["aws", "kubernetes"],             "tags": ["aws", "kubernetes"]},
    "sqs":               {"cats": ["aws"],                           "tags": ["aws"]},
    "dynamodb":          {"cats": ["aws", "databases"],              "tags": ["aws", "database"]},
    "kms":               {"cats": ["aws", "security"],               "tags": ["aws", "security", "iam"]},
    "codedeploy":        {"cats": ["aws", "cicd"],                   "tags": ["aws", "cicd"]},
    "codepipeline":      {"cats": ["aws", "cicd"],                   "tags": ["aws", "cicd"]},
    "cloudwatch":        {"cats": ["aws", "monitoring"],             "tags": ["aws", "monitoring"]},
    "route53":           {"cats": ["aws"],                           "tags": ["aws"]},
    "fargate":           {"cats": ["aws", "docker"],                 "tags": ["aws", "docker"]},
    "aurora":            {"cats": ["aws", "databases"],              "tags": ["aws", "database"]},
    "parameter-store":   {"cats": ["aws", "security"],               "tags": ["aws", "security"]},
    "iam":               {"cats": ["aws", "security"],               "tags": ["iam", "aws", "security"]},
    "ses":               {"cats": ["aws"],                           "tags": ["aws"]},
    # GCP
    "gcp":               {"cats": ["gcp"],                           "tags": ["gcp"]},
    "google-cloud":      {"cats": ["gcp"],                           "tags": ["gcp"]},
    "gke":               {"cats": ["gcp", "kubernetes"],             "tags": ["gke", "gcp", "kubernetes"]},
    "cloud-run":         {"cats": ["gcp", "serverless"],             "tags": ["gcp", "serverless"]},
    "bigquery":          {"cats": ["gcp", "databases"],              "tags": ["gcp", "database"]},
    # Azure
    "azure":             {"cats": ["azure"],                         "tags": ["azure"]},
    "aks":               {"cats": ["azure", "kubernetes"],           "tags": ["aks", "azure", "kubernetes"]},
    # Kubernetes
    "kubernetes":        {"cats": ["kubernetes"],                    "tags": ["kubernetes"]},
    "kubectl":           {"cats": ["kubernetes"],                    "tags": ["kubernetes"]},
    "helm":              {"cats": ["kubernetes"],                    "tags": ["helm", "kubernetes"]},
    "kustomize":         {"cats": ["kubernetes"],                    "tags": ["kubernetes"]},
    "operator":          {"cats": ["kubernetes"],                    "tags": ["kubernetes"]},
    "rbac":              {"cats": ["kubernetes", "security"],        "tags": ["kubernetes", "security"]},
    "admission":         {"cats": ["kubernetes"],                    "tags": ["kubernetes"]},
    "tekton":            {"cats": ["kubernetes", "cicd"],            "tags": ["kubernetes", "cicd"]},
    "argocd":  {"cats": ["kubernetes", "cicd", "platform-engineering"], "tags": ["kubernetes", "cicd", "gitops"]},
    "argo-cd": {"cats": ["kubernetes", "cicd", "platform-engineering"], "tags": ["kubernetes", "cicd", "gitops"]},
    "crossplane":        {"cats": ["kubernetes", "platform-engineering"], "tags": ["kubernetes"]},
    "cilium":            {"cats": ["kubernetes", "service-mesh"],    "tags": ["kubernetes", "service-mesh"]},
    "istio":             {"cats": ["kubernetes", "service-mesh"],    "tags": ["kubernetes", "service-mesh"]},
    "chaos":             {"cats": ["kubernetes", "platform-engineering"], "tags": ["kubernetes"]},
    "writing-kubernetes":{"cats": ["kubernetes"],                    "tags": ["kubernetes", "golang"]},
    "kubernetes-controllers": {"cats": ["kubernetes"],               "tags": ["kubernetes", "golang"]},
    "admission-webhooks":{"cats": ["kubernetes"],                    "tags": ["kubernetes", "golang"]},
    "ebpf":              {"cats": ["kubernetes", "service-mesh"],    "tags": ["kubernetes", "service-mesh"]},
    # Go / Golang
    "golang":            {"cats": ["golang"],                        "tags": ["golang"]},
    "go-modules":        {"cats": ["golang"],                        "tags": ["golang"]},
    "go-context":        {"cats": ["golang"],                        "tags": ["golang"]},
    "go-fuzz":           {"cats": ["golang"],                        "tags": ["golang"]},
    "go-1-16":           {"cats": ["golang"],                        "tags": ["golang"]},
    "grpc":              {"cats": ["golang", "service-mesh"],        "tags": ["golang", "service-mesh"]},
    "grpc-in-go":        {"cats": ["golang"],                        "tags": ["golang", "service-mesh"]},
    "grpc-mtls": {"cats": ["golang", "security", "service-mesh"], "tags": ["golang", "security", "service-mesh"]},
    "fips":              {"cats": ["golang", "security"],            "tags": ["golang", "security"]},
    "envelope-encryption":{"cats": ["security", "golang"],          "tags": ["security", "golang"]},
    "key-rotation":      {"cats": ["security", "golang"],           "tags": ["security", "golang"]},
    "opentelemetry":     {"cats": ["monitoring", "golang"],         "tags": ["monitoring", "golang"]},
    # Security
    "mtls":              {"cats": ["security", "service-mesh"],      "tags": ["security", "service-mesh"]},
    "key-protect":       {"cats": ["security", "ibm-cloud", "golang"], "tags": ["security", "ibm-cloud", "golang"]},
    "ibm-key":           {"cats": ["security", "ibm-cloud", "golang"], "tags": ["security", "ibm-cloud", "golang"]},
    "hsm":               {"cats": ["security", "ibm-cloud"],         "tags": ["security", "ibm-cloud"]},
    "vault":             {"cats": ["security"],                      "tags": ["security"]},
    "selinux":           {"cats": ["linux", "security"],             "tags": ["linux", "security"]},
    "opa":  {"cats": ["kubernetes", "platform-engineering", "security"], "tags": ["kubernetes", "security"]},
    "rego": {"cats": ["kubernetes", "platform-engineering", "security"], "tags": ["kubernetes", "security"]},
    # Python
    "python":            {"cats": ["python"],                        "tags": ["python"]},
    "boto3":             {"cats": ["aws", "python"],                 "tags": ["aws", "python"]},
    "flask":             {"cats": ["python"],                        "tags": ["python"]},
    "django":            {"cats": ["python"],                        "tags": ["python"]},
    "selenium":          {"cats": ["python"],                        "tags": ["python"]},
    "sqlalchemy":        {"cats": ["databases", "python"],           "tags": ["database", "python"]},
    "chatastic":         {"cats": ["chatops", "python"],             "tags": ["chatops", "python"]},
    "structured-logging":{"cats": ["monitoring", "python"],         "tags": ["monitoring", "python"]},
    # Terraform / IaC
    "terraform":         {"cats": ["terraform"],                     "tags": ["terraform"]},
    "pulumi":            {"cats": ["terraform", "aws"],              "tags": ["terraform", "aws"]},
    # Docker / containers
    "docker":            {"cats": ["docker"],                        "tags": ["docker"]},
    "container":         {"cats": ["docker"],                        "tags": ["docker"]},
    "microservices":     {"cats": ["docker", "kubernetes"],          "tags": ["docker", "kubernetes"]},
    "cron":              {"cats": ["linux", "docker"],               "tags": ["linux", "docker"]},
    # Monitoring
    "monitoring":        {"cats": ["monitoring"],                    "tags": ["monitoring"]},
    "prometheus": {"cats": ["monitoring", "kubernetes"], "tags": ["prometheus", "monitoring", "kubernetes"]},
    "grafana":           {"cats": ["monitoring"],                    "tags": ["grafana", "monitoring"]},
    "elk":               {"cats": ["monitoring"],                    "tags": ["monitoring"]},
    "logstash":          {"cats": ["monitoring"],                    "tags": ["monitoring"]},
    "kibana":            {"cats": ["monitoring"],                    "tags": ["monitoring"]},
    "shinken":           {"cats": ["monitoring", "linux"],           "tags": ["monitoring", "linux"]},
    "omd":               {"cats": ["monitoring", "linux"],           "tags": ["monitoring", "linux"]},
    "zabbix":            {"cats": ["monitoring"],                    "tags": ["monitoring"]},
    # Platform Engineering
    "platform-engineering": {"cats": ["platform-engineering"],      "tags": []},
    "platform-team":     {"cats": ["platform-engineering"],         "tags": []},
    "developer-portal":  {"cats": ["platform-engineering"],         "tags": []},
    "gitops":            {"cats": ["platform-engineering", "cicd"],  "tags": ["gitops", "cicd"]},
    "backstage":         {"cats": ["platform-engineering"],         "tags": []},
    # ChatOps
    "chatops":           {"cats": ["chatops"],                       "tags": ["chatops"]},
    "slack":             {"cats": ["chatops"],                       "tags": ["chatops"]},
    # Databases
    "mysql":             {"cats": ["databases"],                     "tags": ["mysql", "database"]},
    "postgres":          {"cats": ["databases"],                     "tags": ["postgresql", "database"]},
    "postgresql":        {"cats": ["databases"],                     "tags": ["postgresql", "database"]},
    "rds":               {"cats": ["databases", "aws"],              "tags": ["aws", "database"]},
    "mysql-basic":       {"cats": ["databases"],                     "tags": ["mysql", "database"]},
    "mysql-server":      {"cats": ["databases"],                     "tags": ["mysql", "database"]},
    "redis":             {"cats": ["databases"],                     "tags": ["redis", "database"]},
    # Linux / Sysadmin
    "bash":              {"cats": ["linux"],                         "tags": ["bash", "linux"]},
    "apache":            {"cats": ["linux"],                         "tags": ["linux"]},
    "nginx":             {"cats": ["linux"],                         "tags": ["nginx", "linux"]},
    "centos":            {"cats": ["linux"],                         "tags": ["linux"]},
    "monit":             {"cats": ["linux"],                         "tags": ["linux"]},
    # CI/CD
    "bitbucket":         {"cats": ["cicd"],                          "tags": ["cicd"]},
    "github-actions":    {"cats": ["cicd"],                          "tags": ["cicd"]},
    "jenkins":           {"cats": ["cicd"],                          "tags": ["cicd"]},
    # IBM Cloud
    "ibm":               {"cats": ["ibm-cloud"],                     "tags": ["ibm-cloud"]},
    "acadia":            {"cats": ["ibm-cloud"],                     "tags": ["ibm-cloud"]},
    # Serverless
    "serverless":        {"cats": ["serverless"],                    "tags": ["serverless"]},
    # SaltStack
    "saltstack":         {"cats": ["saltstack"],                     "tags": ["saltstack"]},
    "salt-stack":        {"cats": ["saltstack"],                     "tags": ["saltstack"]},
    # Ansible
    "ansible":           {"cats": ["ansible"],                       "tags": ["ansible"]},
    # Web / CMS
    "drupal":            {"cats": ["web"],                           "tags": ["drupal"]},
    "wordpress":         {"cats": ["web"],                           "tags": ["wordpress"]},
    "craigslist":        {"cats": ["web"],                           "tags": ["web"]},
    "linkedin":          {"cats": ["web"],                           "tags": ["web"]},
    "php":               {"cats": ["web"],                           "tags": ["php"]},
    # JavaScript
    "javascript":        {"cats": ["web"],                           "tags": ["javascript"]},
    "jquery":            {"cats": ["web"],                           "tags": ["javascript"]},
    "nodejs":            {"cats": ["web"],                           "tags": ["javascript"]},
}

def get_matches(slug, title):
    """Return (matched_cat_slugs, matched_tag_slugs) for a post."""
    text = (slug + " " + title).lower()
    cats, tags = set(), set()
    for keyword, mapping in RULES.items():
        if keyword in text:
            cats.update(mapping["cats"])
            tags.update(mapping["tags"])
    return cats, tags


def run(retag_all: bool = False, dry_run: bool = False):
    conn = psycopg2.connect(DB_DSN, cursor_factory=psycopg2.extras.RealDictCursor)
    cur  = conn.cursor()

    if not dry_run:
        # Seed categories
        for name, slug, desc in CATEGORIES:
            cur.execute("""
                INSERT INTO categories (name, slug, description)
                VALUES (%s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name, description=EXCLUDED.description
            """, (name, slug, desc))

        # Seed tags
        for name, slug in TAGS:
            cur.execute("""
                INSERT INTO tags (name, slug)
                VALUES (%s, %s)
                ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name
            """, (name, slug))

        conn.commit()
        print(f"Seeded {len(CATEGORIES)} categories, {len(TAGS)} tags")

        # Build slug → id maps
        cur.execute("SELECT slug, id FROM categories")
        cat_map = {row["slug"]: row["id"] for row in cur.fetchall()}

        cur.execute("SELECT slug, id FROM tags")
        tag_map = {row["slug"]: row["id"] for row in cur.fetchall()}
    else:
        cat_map, tag_map = {}, {}

    # Fetch posts to process
    if retag_all:
        cur.execute("SELECT id, slug, title FROM posts WHERE status='published'")
    else:
        cur.execute("""
            SELECT p.id, p.slug, p.title FROM posts p
            WHERE  p.status = 'published'
              AND  NOT EXISTS (SELECT 1 FROM post_tags       WHERE post_id = p.id)
              AND  NOT EXISTS (SELECT 1 FROM post_categories WHERE post_id = p.id)
        """)

    posts = cur.fetchall()
    print(f"Processing {len(posts)} post(s)  [retag_all={retag_all}, dry_run={dry_run}]")

    tagged = 0
    for post in posts:
        post_id = post["id"]
        slug    = post["slug"]
        title   = post["title"]

        matched_cats, matched_tags = get_matches(slug, title)
        if not matched_cats and not matched_tags:
            continue

        print(f"  ✓ {slug!r}")
        if matched_cats:
            print(f"      categories: {', '.join(sorted(matched_cats))}")
        if matched_tags:
            print(f"      tags      : {', '.join(sorted(matched_tags))}")

        if dry_run:
            continue

        try:
            if retag_all:
                cur.execute("DELETE FROM post_categories WHERE post_id = %s", (post_id,))
                cur.execute("DELETE FROM post_tags       WHERE post_id = %s", (post_id,))

            for cs in matched_cats:
                cat_id = cat_map.get(cs)
                if cat_id:
                    cur.execute(
                        "INSERT INTO post_categories (post_id, category_id) VALUES (%s, %s)"
                        " ON CONFLICT DO NOTHING",
                        (post_id, cat_id),
                    )

            for ts in matched_tags:
                tag_id = tag_map.get(ts)
                if tag_id:
                    cur.execute(
                        "INSERT INTO post_tags (post_id, tag_id) VALUES (%s, %s)"
                        " ON CONFLICT DO NOTHING",
                        (post_id, tag_id),
                    )

            tagged += 1
        except Exception as exc:
            conn.rollback()
            print(f"  ✗ {slug}: {exc}", file=sys.stderr)
            continue

    if not dry_run:
        conn.commit()

    cur.close()
    conn.close()
    print(f"\nTagged {tagged} post(s).")


if __name__ == "__main__":
    retag_all = "--all"     in sys.argv
    dry_run   = "--dry-run" in sys.argv
    run(retag_all=retag_all, dry_run=dry_run)
