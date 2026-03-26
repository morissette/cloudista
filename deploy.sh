#!/usr/bin/env bash
# deploy.sh — push Cloudista API + static site to production
#
# Usage:
#   bash deploy.sh          # full deploy
#   bash deploy.sh --api    # API only (skip static files + nginx)
#   bash deploy.sh --site   # static files only
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SSH_KEY="${SSH_KEY_PATH:-$HOME/.ssh/mhorg.pem}"
SSH_HOST="${DEPLOY_SSH_HOST:-ec2-user@vabch.org}"
REMOTE_WEB="/www/cloudista.org"
REMOTE_API="/www/cloudista.org/api"
CONTAINER="cloudista-api"
HOST_PORT=8000

MODE="${1:-}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
step() { echo ""; echo "==> $*"; }
ok()   { echo "    ✓ $*"; }

# Trust-on-first-use (TOFU): add host key on first run; refuse if it changes thereafter.
# Note: the first run is not MITM-protected — verify the fingerprint manually if needed.
_trust_host() {
  local known="$HOME/.ssh/known_hosts"
  local host="${SSH_HOST#*@}"  # strip user@ prefix
  mkdir -p "$HOME/.ssh"
  if ! ssh-keygen -F "$host" -f "$known" &>/dev/null; then
    ssh-keyscan -H "$host" >> "$known" 2>/dev/null && echo "    ✓ Host key added: $host"
  fi
}
_trust_host

ssh_cmd() { ssh -i "$SSH_KEY" "$SSH_HOST" "$@"; }
scp_file() { scp -i "$SSH_KEY" "$@"; }

# Compute deploy hash once — used in all cache-busting sed substitutions below
DEPLOY_HASH=$(git rev-parse --short HEAD)
ok "Deploy hash: ${DEPLOY_HASH}"

# ---------------------------------------------------------------------------
# 1. Deploy static site files
# ---------------------------------------------------------------------------
if [[ "$MODE" != "--api" ]]; then
  step "Deploying static site files..."
  # Inject hash into site/index.html so main.js and style.css URLs are cache-busted
  sed "s/__DEPLOY_HASH__/${DEPLOY_HASH}/g" site/index.html > /tmp/site-index.html
  # /www/ is root-owned — scp to tmp, then sudo mv into place
  scp_file /tmp/site-index.html site/style.css site/main.js site/robots.txt \
    site/privacy.html site/terms.html \
    site/assets/og-image.png \
    site/assets/favicon.svg site/assets/favicon.ico site/assets/favicon-32x32.png \
    site/assets/favicon-192x192.png site/assets/apple-touch-icon.png site/assets/site.webmanifest \
    "$SSH_HOST:/tmp/"
  ssh_cmd "sudo mv /tmp/site-index.html $REMOTE_WEB/index.html && \
    sudo mv /tmp/style.css /tmp/main.js \
    /tmp/robots.txt /tmp/og-image.png \
    /tmp/privacy.html /tmp/terms.html \
    /tmp/favicon.svg /tmp/favicon.ico /tmp/favicon-32x32.png \
    /tmp/favicon-192x192.png /tmp/apple-touch-icon.png /tmp/site.webmanifest \
    $REMOTE_WEB/"
  ok "static files uploaded (incl. favicons, deploy hash: ${DEPLOY_HASH})"

  step "Deploying blog static files..."
  ssh_cmd "sudo mkdir -p $REMOTE_WEB/blog && sudo chown ec2-user:ec2-user $REMOTE_WEB/blog"
  # Inject git hash into HTML so browsers bust the cache on each deploy
  sed "s/__DEPLOY_HASH__/${DEPLOY_HASH}/g" blog-site/index.html   > /tmp/blog-index.html
  sed "s/__DEPLOY_HASH__/${DEPLOY_HASH}/g" blog-site/post.html    > /tmp/blog-post.html
  sed "s/__DEPLOY_HASH__/${DEPLOY_HASH}/g" blog-site/archive.html > /tmp/blog-archive.html
  scp_file /tmp/blog-index.html /tmp/blog-post.html /tmp/blog-archive.html blog-site/blog.js "$SSH_HOST:/tmp/"
  ssh_cmd "sudo mv /tmp/blog-index.html $REMOTE_WEB/blog/index.html && sudo mv /tmp/blog-post.html $REMOTE_WEB/blog/post.html && sudo mv /tmp/blog-archive.html $REMOTE_WEB/blog/archive.html && sudo mv /tmp/blog.js $REMOTE_WEB/blog/blog.js"
  ok "blog pages uploaded"
fi

# ---------------------------------------------------------------------------
# 2. Deploy API
# ---------------------------------------------------------------------------
if [[ "$MODE" != "--site" ]]; then

  step "Preparing remote API directory..."
  ssh_cmd "sudo mkdir -p $REMOTE_API && sudo chown ec2-user:ec2-user $REMOTE_API"
  ok "Directory ready: $REMOTE_API"

  step "Uploading API source files..."
  # Inject deploy hash into SSR template so server-rendered pages get cache-busted asset URLs
  sed "s/__DEPLOY_HASH__/${DEPLOY_HASH}/g" api/blog_routes.py > /tmp/blog_routes.py
  scp_file api/main.py api/email_template.py /tmp/blog_routes.py \
    api/config.py api/dependencies.py api/schemas.py \
    api/Pipfile api/Pipfile.lock api/Dockerfile "$SSH_HOST:$REMOTE_API/"
  # Scripts dir (batch tools — sudo needed for /www/)
  ssh_cmd "sudo mkdir -p $REMOTE_WEB/scripts && sudo chown ec2-user:ec2-user $REMOTE_WEB/scripts"
  scp_file scripts/verify_pending.py "$SSH_HOST:$REMOTE_WEB/scripts/"
  ok "API source + scripts uploaded"

  step "Ensuring API .env exists..."
  ssh_cmd bash << 'REMOTE'
  ENV_FILE="/www/cloudista.org/api/.env"
  if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" << 'EOF'
BLOG_DB_HOST=localhost
BLOG_DB_PORT=5433
BLOG_DB_USER=cloudista
# REQUIRED: set BLOG_DB_PASSWORD before starting the container or startup will fail
BLOG_DB_PASSWORD=
BLOG_DB_NAME=cloudista
AWS_REGION=us-east-1
FROM_EMAIL=noreply@cloudista.org
CONFIRM_BASE_URL=https://cloudista.org/api/confirm
SITE_URL=https://cloudista.org
TURNSTILE_SECRET=
SES_TOPIC_ARN=
EOF
    chmod 600 "$ENV_FILE"
    echo "    ✓ .env scaffold created — set BLOG_DB_PASSWORD before starting"
    echo "    ! WARNING: container will fail to start until BLOG_DB_PASSWORD is set"
  else
    # Verify the password is set in the existing file before deploying
    if grep -q "^BLOG_DB_PASSWORD=$" "$ENV_FILE"; then
      echo "    ! WARNING: BLOG_DB_PASSWORD is empty in $ENV_FILE — container will fail at startup"
    fi
    echo "    ✓ .env already exists — preserving"
  fi
REMOTE

  # Capture previous image ID so we can roll back if the health check fails
  PREV_IMAGE=$(ssh_cmd "sudo docker inspect --format='{{.Image}}' $CONTAINER 2>/dev/null || true")

  step "Building Docker image..."
  ssh_cmd "cd $REMOTE_API && sudo docker build -t $CONTAINER ."
  ok "Image built: $CONTAINER"

  step "Restarting API container..."
  ssh_cmd bash << REMOTE
    sudo docker stop $CONTAINER 2>/dev/null && echo "    stopped old container" || true
    sudo docker rm   $CONTAINER 2>/dev/null || true
    # --network host: container shares the host network stack.
    # Uvicorn binds to 0.0.0.0:8000 on the host directly.
    sudo docker run -d \\
      --name            $CONTAINER \\
      --restart         unless-stopped \\
      --network         host \\
      --env-file        $REMOTE_API/.env \\
      $CONTAINER
REMOTE
  ok "Container started on 127.0.0.1:$HOST_PORT"

  # Give uvicorn a moment to start before the health check
  sleep 2

  step "Verifying container health..."
  ssh_cmd "sudo docker ps --filter name=$CONTAINER --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
  if ! ssh_cmd "curl -sf http://127.0.0.1:$HOST_PORT/api/health"; then
    echo "    !!! health check failed"
    if [ -n "$PREV_IMAGE" ]; then
      echo "    rolling back to previous image: $PREV_IMAGE"
      ssh_cmd bash << ROLLBACK
        sudo docker stop $CONTAINER 2>/dev/null || true
        sudo docker rm   $CONTAINER 2>/dev/null || true
        sudo docker run -d \\
          --name            $CONTAINER \\
          --restart         unless-stopped \\
          --network         host \\
          --env-file        $REMOTE_API/.env \\
          $PREV_IMAGE
ROLLBACK
      echo "    rolled back — check: sudo docker logs $CONTAINER"
    else
      echo "    no previous image to roll back to"
      echo "    check: sudo docker logs $CONTAINER"
    fi
    exit 1
  fi
  ok "/api/health OK"

fi

# ---------------------------------------------------------------------------
# 3. nginx config — always deploy so infra/ changes take effect in any mode
# ---------------------------------------------------------------------------
step "Updating nginx config..."
scp_file infra/nginx-cloudista.conf "$SSH_HOST:/tmp/cloudista.conf"
ssh_cmd "sudo cp /tmp/cloudista.conf /etc/nginx/conf.d/cloudista.conf"
# Test config before reloading; abort if invalid to avoid taking down the site
ssh_cmd "sudo nginx -t" || { echo "!!! nginx config test failed — aborting reload"; exit 1; }
ssh_cmd "sudo nginx -s reload"
ok "nginx reloaded"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "==> Deployment complete!"
echo ""
echo "    Live:         https://cloudista.org"
echo "    Health check: https://cloudista.org/api/health"
echo "    API logs:     ssh -i ~/.ssh/mhorg.pem ec2-user@vabch.org 'sudo docker logs -f $CONTAINER'"
echo ""
