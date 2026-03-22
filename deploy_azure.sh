#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy_azure.sh — One-shot Azure Container Apps deployment for Irminsul
#
# Prerequisites:
#   - Azure CLI installed: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli
#   - Logged in: az login
#   - Subscription active: az account show
#
# Usage:
#   export PINECONE_API_KEY=your_key
#   export GROQ_API_KEY=your_key
#   chmod +x deploy_azure.sh
#   ./deploy_azure.sh
#
# What this script does:
#   1. Creates a resource group in East US
#   2. Creates an Azure Container Registry (ACR)
#   3. Builds the Docker image via ACR Tasks (no local Docker build needed)
#   4. Creates a Container Apps environment
#   5. Deploys the container with secrets injected as env vars
#   6. Prints the live HTTPS URL
#
# Cost note:
#   This stack (Groq backend, no GPU) runs on a consumption-plan Container App.
#   Estimated cost: ~$0/month on free tier (180,000 vCPU-seconds/month free).
#   GPU-accelerated inference (local Llama backend) requires NC-series instances
#   (~$0.50-1.50/hr) which is not cost-effective for a portfolio project.
#   See DEPLOYMENT.md for the full cost analysis.
# ─────────────────────────────────────────────────────────────────────────────

set -e  # exit on any error

# ── Configuration ──────────────────────────────────────────────────────────────
RESOURCE_GROUP="irminsul-rg"
LOCATION="eastus"
ACR_NAME="irminsulacr"             # must be globally unique, lowercase alphanumeric
ENVIRONMENT="irminsul-env"
APP_NAME="irminsul"
IMAGE_TAG="latest"

# ── Validate required secrets ──────────────────────────────────────────────────
if [[ -z "$PINECONE_API_KEY" ]]; then
  echo "ERROR: PINECONE_API_KEY environment variable is not set."
  echo "  export PINECONE_API_KEY=your_key"
  exit 1
fi

if [[ -z "$GROQ_API_KEY" ]]; then
  echo "ERROR: GROQ_API_KEY environment variable is not set."
  echo "  export GROQ_API_KEY=your_key"
  exit 1
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Irminsul — Azure Container Apps Deployment"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 1: Resource Group ─────────────────────────────────────────────────────
echo "[1/5] Creating resource group: $RESOURCE_GROUP"
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none
echo "      ✓ Resource group ready"

# ── Step 2: Azure Container Registry ──────────────────────────────────────────
echo "[2/5] Creating container registry: $ACR_NAME"
az acr create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ACR_NAME" \
  --sku Basic \
  --admin-enabled true \
  --output none
echo "      ✓ ACR created"

# ── Step 3: Build image via ACR Tasks (cloud build — no local Docker needed) ───
echo "[3/5] Building Docker image via ACR Tasks..."
echo "      This uploads your source code to Azure and builds in the cloud."
az acr build \
  --registry "$ACR_NAME" \
  --image "${APP_NAME}:${IMAGE_TAG}" \
  .
echo "      ✓ Image built and pushed: ${ACR_NAME}.azurecr.io/${APP_NAME}:${IMAGE_TAG}"

# ── Step 4: Container Apps Environment ────────────────────────────────────────
echo "[4/5] Creating Container Apps environment: $ENVIRONMENT"
az containerapp env create \
  --name "$ENVIRONMENT" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none
echo "      ✓ Environment ready"

# ── Step 5: Deploy Container App ──────────────────────────────────────────────
echo "[5/5] Deploying container app: $APP_NAME"

# Get ACR credentials for pulling the image
ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer --output tsv)
ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --query username --output tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" --output tsv)

az containerapp create \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENVIRONMENT" \
  --image "${ACR_LOGIN_SERVER}/${APP_NAME}:${IMAGE_TAG}" \
  --registry-server "$ACR_LOGIN_SERVER" \
  --registry-username "$ACR_USERNAME" \
  --registry-password "$ACR_PASSWORD" \
  --target-port 8000 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 3 \
  --cpu 1.0 \
  --memory 2.0Gi \
  --env-vars \
      PINECONE_API_KEY=secretref:pinecone-key \
      GROQ_API_KEY=secretref:groq-key \
      PINECONE_INDEX=llmops-rag \
      LLM_BACKEND=groq \
      EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
  --secrets \
      pinecone-key="$PINECONE_API_KEY" \
      groq-key="$GROQ_API_KEY" \
  --output none

echo "      ✓ Container app deployed"

# ── Print live URL ─────────────────────────────────────────────────────────────
LIVE_URL=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" \
  --output tsv)

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Deployment complete!"
echo ""
echo "  Live URL:  https://${LIVE_URL}"
echo "  Health:    https://${LIVE_URL}/health"
echo "  API docs:  https://${LIVE_URL}/docs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  To tear down everything and stop billing:"
echo "  az group delete --name $RESOURCE_GROUP --yes --no-wait"
echo ""
