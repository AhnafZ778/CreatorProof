#!/usr/bin/env bash
# deploy/azure/setup-vm.sh
# Creates an Azure VM and installs Docker + Nginx for CreatorProof.
#
# Prerequisites:
#   - Azure CLI installed (https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
#   - Logged in: az login
#   - Azure for Students subscription active
#
# Usage:
#   chmod +x deploy/azure/setup-vm.sh
#   ./deploy/azure/setup-vm.sh

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────
RESOURCE_GROUP="${RESOURCE_GROUP:-creatorproof-rg}"
LOCATION="${LOCATION:-eastus}"
VM_NAME="${VM_NAME:-creatorproof-vm}"
VM_SIZE="${VM_SIZE:-Standard_B2ms}"     # 2 vCPU, 8GB RAM (~$60/mo)
ADMIN_USER="${ADMIN_USER:-farhan}"
DISK_SIZE="${DISK_SIZE:-128}"            # GB, Premium SSD

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Preflight ────────────────────────────────────────────────────────
if ! command -v az &>/dev/null; then
    error "Azure CLI not found. Install: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli"
    exit 1
fi

if ! az account show &>/dev/null; then
    error "Not logged in. Run: az login"
    exit 1
fi

SUB=$(az account show --query "name" -o tsv 2>/dev/null)
info "Using Azure subscription: $SUB"
info "Creating resource group: $RESOURCE_GROUP in $LOCATION"

# ── Resource Group ───────────────────────────────────────────────────
az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none

info "Resource group created."

# ── Network Security Group (firewall rules) ──────────────────────────
NSG_NAME="${VM_NAME}-nsg"

az network nsg create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$NSG_NAME" \
    --location "$LOCATION" \
    --output none

# SSH
az network nsg rule create \
    --resource-group "$RESOURCE_GROUP" \
    --nsg-name "$NSG_NAME" \
    --name AllowSSH \
    --priority 1000 \
    --destination-port-ranges 22 \
    --protocol Tcp \
    --access Allow \
    --direction Inbound \
    --output none

# HTTP
az network nsg rule create \
    --resource-group "$RESOURCE_GROUP" \
    --nsg-name "$NSG_NAME" \
    --name AllowHTTP \
    --priority 1100 \
    --destination-port-ranges 80 \
    --protocol Tcp \
    --access Allow \
    --direction Inbound \
    --output none

# HTTPS
az network nsg rule create \
    --resource-group "$RESOURCE_GROUP" \
    --nsg-name "$NSG_NAME" \
    --name AllowHTTPS \
    --priority 1200 \
    --destination-port-ranges 443 \
    --protocol Tcp \
    --access Allow \
    --direction Inbound \
    --output none

info "NSG created with SSH (22), HTTP (80), HTTPS (443) rules."

# ── Create VM ────────────────────────────────────────────────────────
info "Creating VM: $VM_NAME ($VM_SIZE, ${DISK_SIZE}GB) ..."
info "This takes 2-5 minutes..."

az vm create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --image UbuntuLTS \
    --size "$VM_SIZE" \
    --admin-username "$ADMIN_USER" \
    --generate-ssh-keys \
    --storage-sku Premium_LRS \
    --os-disk-size-gb "$DISK_SIZE" \
    --nsg "$NSG_NAME" \
    --public-ip-sku Standard \
    --output json \
    --query "{ip: publicIpAddress, fqdn: fqdn}" > /tmp/azure-vm-output.json

VM_IP=$(jq -r '.ip' /tmp/azure-vm-output.json)
info "VM created. Public IP: $VM_IP"

# ── Install Docker + Nginx on VM ─────────────────────────────────────
info "Installing Docker and Nginx on the VM..."

ssh -o StrictHostKeyChecking=no "$ADMIN_USER@$VM_IP" bash <<'REMOTE_SCRIPT'
set -euo pipefail

# Update system
sudo apt-get update -y
sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"

# Install Nginx
sudo apt-get install -y nginx

# Install jq (useful for debugging)
sudo apt-get install -y jq

# Enable and start services
sudo systemctl enable docker nginx
sudo systemctl start docker nginx

# Create app directory
mkdir -p ~/CreatorProof

echo "Docker and Nginx installed successfully."
REMOTE_SCRIPT

info "VM setup complete!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  VM IP:  $VM_IP"
echo "  SSH:    ssh $ADMIN_USER@$VM_IP"
echo "  Next:   Run deploy/azure/deploy.sh to deploy the app"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Save IP for deploy.sh
echo "$VM_IP" > /home/farhan/CreatorProof/deploy/azure/.vm-ip
