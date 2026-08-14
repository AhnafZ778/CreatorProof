# Azure Deployment Guide

Deploy CreatorProof to a single Azure VM with Docker Compose.

## Cost Estimate (~$74/month)

| Resource | Spec | Monthly |
|----------|------|---------|
| Azure VM | B2ms (2 vCPU, 8GB RAM) | ~$60 |
| Premium SSD | 128GB | ~$10 |
| Bandwidth | ~50GB | ~$4 |

Fits within the **Azure for Students $100/month** credit.

## Quick Start

### 1. Activate Azure for Students

Go to [azure.microsoft.com/en-us/free/students](https://azure.microsoft.com/en-us/free/students)
and activate your $100/month credit with your student email.

### 2. Install Azure CLI

```bash
# macOS
brew install azure-cli

# Linux (Ubuntu/Debian)
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Windows
winget install Microsoft.AzureCLI
```

### 3. Login to Azure

```bash
az login
```

### 4. Create the VM

```bash
cd /home/farhan/CreatorProof
chmod +x deploy/azure/setup-vm.sh
./deploy/azure/setup-vm.sh
```

This creates:
- Resource group in East US
- B2ms VM (8GB RAM) with Ubuntu
- Network security group (SSH, HTTP, HTTPS)
- Installs Docker and Nginx on the VM

### 5. Configure Secrets

```bash
# Generate secrets
echo "POSTGRES_OWNER=$(openssl rand -base64 32)"
echo "POSTGRES_RUNTIME=$(openssl rand -base64 32)"
echo "DEV_API_KEY=$(openssl rand -hex 32)"
echo "API_KEY_PEPPER=$(openssl rand -hex 16)"
echo "SIGNING_KEY=$(openssl rand -hex 32)"

# Copy and edit the env file
cp .env.production.example .env.production
nano .env.production  # paste the generated secrets
```

### 6. Deploy

```bash
chmod +x deploy/azure/deploy.sh
./deploy/azure/deploy.sh
```

Your app will be at `http://<vm-ip>`.

### 7. (Optional) Add HTTPS with a Domain

```bash
# Point your domain's A record to the VM IP, then:
ssh farhan@<vm-ip>
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d api.yourdomain.com
```

## Managing the Deployment

```bash
# SSH into the VM
ssh farhan@<vm-ip>

# Check service status
cd ~/CreatorProof && docker compose ps

# View logs
docker compose logs -f api
docker compose logs -f web
docker compose logs -f worker

# Restart a service
docker compose restart api

# Redeploy after code changes
./deploy/azure/deploy.sh

# Stop everything (saves VM credits)
az vm stop --resource-group creatorproof-rg --name creatorproof-vm

# Start again
az vm start --resource-group creatorproof-rg --name creatorproof-vm
```

## Cost Saving Tips

- **Stop the VM when not in use** — `az vm stop` stops billing for compute (storage still costs ~$10/mo)
- **Use B-series burstable** — cheapest VMs for variable workloads
- **Monitor credits** — check at [azure.microsoft.com/en-us/free/students/account](https://azure.microsoft.com/en-us/free/students/account)
- **Set a budget alert** — `az consumption budget create` to get warned before credits run out

## Architecture

```
Internet
    │
    ▼
┌─────────────────────────────────┐
│  Azure VM (B2ms, 8GB RAM)      │
│                                 │
│  ┌──────────┐  ┌─────────────┐ │
│  │  Nginx   │  │ Docker      │ │
│  │  :80/443 │  │ Compose     │ │
│  │          │  │             │ │
│  │  / ──────────► web:3000   │ │
│  │  /api/ ──────► api:8000   │ │
│  └──────────┘  │ worker      │ │
│                │ postgres    │ │
│                │ redis       │ │
│                └─────────────┘ │
└─────────────────────────────────┘
```
