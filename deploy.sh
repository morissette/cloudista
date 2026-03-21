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
SSH_KEY="$HOME/.ssh/mhorg.pem"
SSH_HOST="ec2-user@vabch.org"
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

ssh_cmd() { ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$SSH_HOST" "$@"; }
scp_file() { scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$@"; }

# ---------------------------------------------------------------------------
# 1. Deploy static site files
# ---------------------------------------------------------------------------
if [[ "$MODE" != "--api" ]]; then
  step "Deploying static site files..."
  # /www/ is root-owned — scp to tmp, then sudo mv into place
  scp_file index.html style.css main.js robots.txt sitemap.xml og-image.png \
    privacy.html terms.html \
    favicon.svg favicon.ico favicon-32x32.png \
    favicon-192x192.png apple-touch-icon.png site.webmanifest \
    "$SSH_HOST:/tmp/"
  ssh_cmd "sudo mv /tmp/index.html /tmp/style.css /tmp/main.js \
    /tmp/robots.txt /tmp/sitemap.xml /tmp/og-image.png \
    /tmp/privacy.html /tmp/terms.html \
    /tmp/favicon.svg /tmp/favicon.ico /tmp/favicon-32x32.png \
    /tmp/favicon-192x192.png /tmp/apple-touch-icon.png /tmp/site.webmanifest \
    $REMOTE_WEB/"
  ok "static files uploaded (incl. favicons)"

  step "Deploying blog static files..."
  ssh_cmd "sudo mkdir -p $REMOTE_WEB/blog && sudo chown ec2-user:ec2-user $REMOTE_WEB/blog"
  scp_file blog-site/index.html blog-site/post.html blog-site/blog.js "$SSH_HOST:/tmp/"
  ssh_cmd "sudo mv /tmp/index.html /tmp/post.html /tmp/blog.js $REMOTE_WEB/blog/"
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
  scp_file api/main.py api/email_template.py api/blog_routes.py \
    api/Pipfile api/Pipfile.lock api/Dockerfile "$SSH_HOST:$REMOTE_API/"
  # Scripts dir (batch tools — sudo needed for /www/)
  ssh_cmd "sudo mkdir -p $REMOTE_WEB/scripts && sudo chown ec2-user:ec2-user $REMOTE_WEB/scripts"
  scp_file scripts/verify_pending.py "$SSH_HOST:$REMOTE_WEB/scripts/"
  ok "API source + scripts uploaded"

  step "Configuring database user..."
  ssh_cmd bash << 'REMOTE'
    ENV_FILE="/www/cloudista.org/api/.env"

    if [ ! -f "$ENV_FILE" ]; then
      # Generate a random password (alphanumeric, safe for shell)
      DB_PASS=$(openssl rand -base64 18 | tr -d '/+=')
      cat > "$ENV_FILE" << EOF
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=cloudista_api
DB_PASSWORD=${DB_PASS}
DB_NAME=cloudista
EOF
      chmod 600 "$ENV_FILE"
      echo "    ✓ .env created with generated password"
    else
      echo "    ✓ .env already exists — preserving"
    fi

    # Append SES / site vars if not already present
    grep -q "AWS_REGION"       "$ENV_FILE" || echo "AWS_REGION=us-east-1"                              >> "$ENV_FILE"
    grep -q "FROM_EMAIL"       "$ENV_FILE" || echo "FROM_EMAIL=noreply@cloudista.org"                  >> "$ENV_FILE"
    grep -q "CONFIRM_BASE_URL" "$ENV_FILE" || echo "CONFIRM_BASE_URL=https://cloudista.org/api/confirm" >> "$ENV_FILE"
    grep -q "SITE_URL"         "$ENV_FILE" || echo "SITE_URL=https://cloudista.org"                    >> "$ENV_FILE"
    grep -q "TURNSTILE_SECRET"  "$ENV_FILE" || echo "TURNSTILE_SECRET="                                  >> "$ENV_FILE"
    grep -q "BLOG_DB_HOST"     "$ENV_FILE" || echo "BLOG_DB_HOST=localhost"                              >> "$ENV_FILE"
    grep -q "BLOG_DB_PORT"     "$ENV_FILE" || echo "BLOG_DB_PORT=5433"                                   >> "$ENV_FILE"
    grep -q "BLOG_DB_USER"     "$ENV_FILE" || echo "BLOG_DB_USER=cloudista"                              >> "$ENV_FILE"
    grep -q "BLOG_DB_PASSWORD" "$ENV_FILE" || echo "BLOG_DB_PASSWORD=cloudista_dev"                      >> "$ENV_FILE"
    grep -q "BLOG_DB_NAME"     "$ENV_FILE" || echo "BLOG_DB_NAME=cloudista"                              >> "$ENV_FILE"
    echo "    ✓ .env vars present"

    # GRANT ... IDENTIFIED BY is the MariaDB 5.5 compatible way to create a
    # user (if not exists) and set permissions in one statement.
    # With --network host the container connects as 127.0.0.1, so @'localhost'
    # covers both TCP and unix-socket connections.
    DB_PASS=$(grep DB_PASSWORD "$ENV_FILE" | cut -d= -f2)
    sudo mysql -e "
      GRANT SELECT, INSERT, UPDATE ON cloudista.* TO 'cloudista_api'@'localhost' IDENTIFIED BY '${DB_PASS}';
      FLUSH PRIVILEGES;
    "
    echo "    ✓ DB user cloudista_api ready"
REMOTE

  step "Building Docker image..."
  ssh_cmd "cd $REMOTE_API && sudo docker build -t $CONTAINER . 2>&1 | tail -5"
  ok "Image built: $CONTAINER"

  step "Restarting API container..."
  ssh_cmd bash << REMOTE
    sudo docker stop $CONTAINER 2>/dev/null && echo "    stopped old container" || true
    sudo docker rm   $CONTAINER 2>/dev/null || true
    # --network host: container shares the host network stack.
    # MariaDB sees connections from 127.0.0.1 (not the bridge IP).
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
  ssh_cmd "curl -sf http://127.0.0.1:$HOST_PORT/api/health && echo '    ✓ /api/health OK'" \
    || echo "    ! health check failed — check: sudo docker logs $CONTAINER"

  step "Updating nginx config..."
  scp_file nginx-cloudista.conf "$SSH_HOST:/tmp/cloudista.conf"
  ssh_cmd "sudo cp /tmp/cloudista.conf /etc/nginx/conf.d/cloudista.conf"
  ssh_cmd "sudo nginx -t && sudo nginx -s reload"
  ok "nginx reloaded"

fi

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
