#!/bin/bash
# Build Docker images for microservices
# Usage: ./build.sh [service_name] [environment]
# Example: ./build.sh auth_service dev
# Example: ./build.sh all dev (builds all services)

set -e

# Service configuration (bash 3.2 compatible)
get_service_port() {
    case "$1" in
        auth_service) echo "8202" ;;
        account_service) echo "8201" ;;
        authorization_service) echo "8203" ;;
        audit_service) echo "8204" ;;
        session_service) echo "8205" ;;
        notification_service) echo "8206" ;;
        payment_service) echo "8207" ;;
        storage_service) echo "8208" ;;
        wallet_service) echo "8209" ;;
        order_service) echo "8210" ;;
        task_service) echo "8211" ;;
        organization_service) echo "8212" ;;
        invitation_service) echo "8213" ;;
        device_service) echo "8220" ;;
        ota_service) echo "8221" ;;
        telemetry_service) echo "8225" ;;
        event_service) echo "8230" ;;
        *) echo "" ;;
    esac
}

SERVICES=(
    "auth_service"
    "account_service"
    "authorization_service"
    "audit_service"
    "session_service"
    "notification_service"
    "payment_service"
    "storage_service"
    "wallet_service"
    "order_service"
    "task_service"
    "organization_service"
    "invitation_service"
    "device_service"
    "ota_service"
    "telemetry_service"
    "event_service"
)

SERVICE_NAME=${1:-all}
ENVIRONMENT=${2:-dev}
IMAGE_TAG=${3:-latest}

# Get project root (2 levels up from deployment/docker)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "Building from: $PROJECT_ROOT"
echo "Environment: $ENVIRONMENT"
echo "Image tag: $IMAGE_TAG"

build_service() {
    local service=$1
    local port=$(get_service_port "$service")

    echo ""
    echo "========================================="
    echo "Building $service (port: $port)"
    echo "========================================="

    # Unified naming: isa-user/{service} (remove _service suffix)
    # Example: auth_service -> isa-user/auth
    local service_short="${service/_service/}"
    local image_base="isa-user/${service_short}"
    local images_to_remove=(
        "${image_base}:${IMAGE_TAG}"
        "${image_base}:${ENVIRONMENT}-${IMAGE_TAG}"
    )

    for img in "${images_to_remove[@]}"; do
        if docker image inspect "$img" >/dev/null 2>&1; then
            echo "🗑️  Removing old image: $img"
            docker rmi "$img" 2>/dev/null || true
        fi
    done

    # Build new image
    docker build \
        -f deployment/docker/Dockerfile.user \
        -t "${image_base}:${IMAGE_TAG}" \
        -t "${image_base}:${ENVIRONMENT}-${IMAGE_TAG}" \
        --build-arg SERVICE_NAME="$service" \
        --build-arg SERVICE_PORT="$port" \
        --build-arg ENVIRONMENT="$ENVIRONMENT" \
        .

    echo "✅ Built: ${image_base}:${IMAGE_TAG}"
}

if [ "$SERVICE_NAME" = "all" ]; then
    echo "Building all microservices..."
    for service in "${SERVICES[@]}"; do
        build_service "$service"
    done
    echo ""
    echo "========================================="
    echo "✅ All services built successfully!"
    echo "========================================="
else
    port=$(get_service_port "$SERVICE_NAME")
    if [ -z "$port" ]; then
        echo "Error: Unknown service '$SERVICE_NAME'"
        echo "Available services: ${SERVICES[*]}"
        exit 1
    fi
    build_service "$SERVICE_NAME"
fi

echo ""
echo "To run a service:"
SERVICE_EXAMPLE=${SERVICE_NAME:-auth_service}
SERVICE_SHORT="${SERVICE_EXAMPLE/_service/}"
PORT_EXAMPLE=$(get_service_port "$SERVICE_EXAMPLE")
echo "  docker run -d \\"
echo "    --name ${SERVICE_EXAMPLE} \\"
echo "    -p ${PORT_EXAMPLE}:${PORT_EXAMPLE} \\"
echo "    --env-file deployment/${ENVIRONMENT}/.env \\"
echo "    isa-user/${SERVICE_SHORT}:${IMAGE_TAG}"
