.DEFAULT_GOAL := help
SHELL         := /bin/bash

SSH_KEY  := $(HOME)/.ssh/mhorg.pem
SSH_HOST := ec2-user@vabch.org
SSH      := ssh -i $(SSH_KEY) -o StrictHostKeyChecking=no $(SSH_HOST)
SCP      := scp -i $(SSH_KEY) -o StrictHostKeyChecking=no

CONTAINER := cloudista-api
API_PORT  := 8000

# ── Colours ────────────────────────────────────────────────────────────────────
ESC   := $(shell printf '\033')
BOLD  := $(ESC)[1m
RESET := $(ESC)[0m
GREEN := $(ESC)[32m
CYAN  := $(ESC)[36m

# ══════════════════════════════════════════════════════════════════════════════
# HELP
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: help
help: ## Show this help message
	@printf "\n  $(BOLD)Cloudista$(RESET) — deployment & development tasks\n"
	@printf "\n  $(BOLD)$(CYAN)Deploy$(RESET)\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | grep -E '^(deploy|site|api|nginx):' \
	  | awk 'BEGIN{FS=":.*?## "}{printf "    $(GREEN)%-20s$(RESET) %s\n", $$1, $$2}'
	@printf "\n  $(BOLD)$(CYAN)Blog content$(RESET)\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | grep -E '^(import|tag|new-post|upload-images|populate-images):' \
	  | awk 'BEGIN{FS=":.*?## "}{printf "    $(GREEN)%-20s$(RESET) %s\n", $$1, $$2}'
	@printf "\n  $(BOLD)$(CYAN)Operations$(RESET)\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | grep -E '^(logs|status|health|ssh|db-shell|restart):' \
	  | awk 'BEGIN{FS=":.*?## "}{printf "    $(GREEN)%-20s$(RESET) %s\n", $$1, $$2}'
	@printf "\n  $(BOLD)$(CYAN)Local dev$(RESET)\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | grep -E '^(dev|dev-api|db-start|db-stop):' \
	  | awk 'BEGIN{FS=":.*?## "}{printf "    $(GREEN)%-20s$(RESET) %s\n", $$1, $$2}'
	@printf "\n"

# ══════════════════════════════════════════════════════════════════════════════
# DEPLOY
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: deploy
deploy: ## Full deploy: static site + API + nginx reload
	bash deploy.sh

.PHONY: site
site: ## Deploy static files only (blog-site/, style.css, etc.)
	bash deploy.sh --site

.PHONY: api
api: ## Deploy API only (rebuild Docker image + restart container)
	bash deploy.sh --api

.PHONY: nginx
nginx: ## Push nginx config and reload (no container rebuild)
	$(SCP) infra/nginx-cloudista.conf $(SSH_HOST):/tmp/cloudista.conf
	$(SSH) "sudo cp /tmp/cloudista.conf /etc/nginx/conf.d/cloudista.conf && \
	        sudo nginx -t && sudo nginx -s reload && echo '✓ nginx reloaded'"

# ══════════════════════════════════════════════════════════════════════════════
# BLOG CONTENT
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: import
import: ## Import all .txt blog posts into local PostgreSQL
	cd blog && python3 import_posts.py

.PHONY: tag
tag: ## Re-run keyword→category tagging on all posts
	cd blog && python3 tag_posts.py

.PHONY: populate-images
populate-images: ## Fetch Unsplash images for posts missing one (needs UNSPLASH_ACCESS_KEY)
ifndef UNSPLASH_ACCESS_KEY
	$(error UNSPLASH_ACCESS_KEY is required — export it or run: UNSPLASH_ACCESS_KEY=xxx make populate-images)
endif
	cd blog && UNSPLASH_ACCESS_KEY=$(UNSPLASH_ACCESS_KEY) python3 populate_images.py $(ARGS)

.PHONY: upload-images
upload-images: ## Upload images/posts/* to production: make upload-images
	@if [ ! -d "images/posts" ]; then echo "No images/posts/ directory found"; exit 1; fi
	$(SSH) "sudo mkdir -p /www/cloudista.org/images/posts && \
	        sudo chown ec2-user:ec2-user /www/cloudista.org/images /www/cloudista.org/images/posts"
	$(SCP) -r images/posts/* $(SSH_HOST):/www/cloudista.org/images/posts/
	@echo "✓ Images uploaded to /www/cloudista.org/images/posts/"

.PHONY: new-post
new-post: ## Scaffold a new post: make new-post SLUG=my-post-title
ifndef SLUG
	$(error SLUG is required — usage: make new-post SLUG=my-post-title)
endif
	@DATE=$$(date +%Y-%m); FILE="blog/$${DATE}-$(SLUG).txt"; \
	if [ -f "$$FILE" ]; then echo "File already exists: $$FILE"; exit 1; fi; \
	printf 'Title: $(SLUG)\nAuthor: Marie H.\nDate: %s\n%s\n\n' \
	  "$$(date +%Y-%m-%d)" \
	  "============================================================" \
	  > "$$FILE"; \
	echo "Created: $$FILE"

# ══════════════════════════════════════════════════════════════════════════════
# OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: logs
logs: ## Tail live API container logs
	$(SSH) "sudo docker logs -f $(CONTAINER)"

.PHONY: status
status: ## Show container status and recent log lines
	$(SSH) "sudo docker ps --filter name=$(CONTAINER) --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' && \
	        echo '' && sudo docker logs $(CONTAINER) --tail 20"

.PHONY: health
health: ## Hit /api/health on the live server
	@curl -sf https://cloudista.org/api/health | python3 -m json.tool \
	  || echo "Health check failed"

.PHONY: ssh
ssh: ## Open an interactive SSH session
	$(SSH)

.PHONY: db-shell
db-shell: ## Open a psql shell on the remote blog database
	$(SSH) "sudo docker exec -it cloudista-db psql -U cloudista -d cloudista"

.PHONY: restart
restart: ## Restart the API container without rebuilding
	$(SSH) "sudo docker restart $(CONTAINER) && echo '✓ restarted'"

# ══════════════════════════════════════════════════════════════════════════════
# LOCAL DEV
# ══════════════════════════════════════════════════════════════════════════════

.PHONY: dev
dev: db-start dev-api ## Start local DB + API together

.PHONY: dev-api
dev-api: ## Run FastAPI locally (hot-reload)
	cd api && BLOG_DB_PORT=5433 BLOG_DB_PASSWORD=cloudista_dev \
	  pipenv run uvicorn main:app --reload --port 8000

.PHONY: db-start
db-start: ## Start local PostgreSQL container (cloudista-db)
	@docker ps --format '{{.Names}}' | grep -q '^cloudista-db$$' \
	  && echo "cloudista-db already running" \
	  || docker start cloudista-db 2>/dev/null \
	  || docker run -d --name cloudista-db \
	       -e POSTGRES_USER=cloudista \
	       -e POSTGRES_PASSWORD=cloudista_dev \
	       -e POSTGRES_DB=cloudista \
	       -p 5433:5432 \
	       postgres:16

.PHONY: db-stop
db-stop: ## Stop local PostgreSQL container
	docker stop cloudista-db
