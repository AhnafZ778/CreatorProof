#!/usr/bin/env bash
# deploy/azure/deploy.sh
# Deploys CreatorProof to an Azure VM via rsync + docker compose.
#
# Prerequisites:
#   - VM already created (run setup-vm.sh first)
#   - .env.production file exists (copy from .env.production.example and fill in secrets)
#   - SSH access to the VM works
#
# Usage:
#   chmod +x deploy/azure/deploy.sh
#   ./deploy/azure/deploy.sh [vm-ip]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Configuration ────────────────────────────────────────────────────
ADMIN_USER="${ADMIN_USER:-farhan}"
VM_IP="${1:-}"
ENV_FILE="$PROJECT_ROOT/.env.production"

# Try to read saved IP
if [[ -z "$VM_IP" && -f "$SCRIPT_DIR/.vm-ip" ]]; then
    VM_IP=$(cat "$SCRIPT_DIR/.vm-ip")
fi

if [[ -z "$VM_IP" ]]; then
    echo "Usage: $0 <vm-ip>"
    echo "  Or set VM_IP env var, or run setup-vm.sh first."
    exit 1
fi

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Preflight ────────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
    error ".env.production not found at: $ENV_FILE"
    echo "  Copy .env.production.example to .env.production and fill in secrets."
    exit 1
fi

if ! ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$ADMIN_USER@$VM_IP" true 2>/dev/null; then
    error "Cannot SSH to $ADMIN_USER@$VM_IP"
    exit 1
fi

info "Deploying CreatorProof to $VM_IP ..."

# ── Sync project files ──────────────────────────────────────────────
info "Syncing project files (this may take a minute on first deploy)..."

rsync -avz --delete \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='__pycache__' \
    --exclude='.venv' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='.env.local' \
    --exclude='.env.development' \
    --exclude='deploy/azure/.vm-ip' \
    "$PROJECT_ROOT/" \
    "$ADMIN_USER@$VM_IP:~/CreatorProof/"

# Copy the production env file
scp "$ENV_FILE" "$ADMIN_USER@$VM_IP:~/CreatorProof/.env"

info "Files synced."

# ── Configure Nginx ──────────────────────────────────────────────────
info "Configuring Nginx reverse proxy..."

scp "$SCRIPT_DIR/nginx.conf" "$ADMIN_USER@$VM_IP:/tmp/creatorproof-nginx.conf"

ssh "$ADMIN_USER@$VM_IP" bash <<'REMOTE_NGINX'
set -euo pipefail

# Install the Nginx config
sudo cp /tmp/creatorproof-nginx.conf /etc/nginx/sites-available/creatorproof
sudo ln -sf /etc/nginx/sites-available/creatorproof /etc/nginx/sites-enabled/creatorproof
sudo rm -f /etc/nginx/sites-enabled/default

# Test and reload
sudo nginx -t
sudo systemctl reload nginx

echo "Nginx configured."
REMOTE_NGINX

info "Nginx configured."

# ── Start services ───────────────────────────────────────────────────
info "Building and starting Docker services..."

ssh "$ADMIN_USER@$VM_IP" bash <<'REMOTE_DEPLOY'
set -euo pipefail
cd ~/CreatorProof

# Build and start (detached, with rebuild)
docker compose build --parallel
docker compose up -d

# Wait for health checks
echo "Waiting for services to become healthy..."
sleep 10

# Show status
docker compose ps
echo ""
echo "Service logs (last 5 lines each):"
for svc in postgres redis api worker web; do
    echo "--- $svc ---"
    docker compose logs --tail=5 "$svc" 2>/dev/null || true
done
REMOTE_DEPLOY

info "Deployment complete!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Frontend:  http://$VM_IP"
echo "  API:       http://$VM_IP/api/"
echo "  SSH:       ssh $ADMIN_USER@$VM_IP"
echo ""
echo "  To add HTTPS, point a domain to $VM_IP and"
echo "  run: ssh $ADMIN_USER@$VM_IP 'sudo apt install certbot python3-certbot-nginx && sudo certbot --nginx'"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
