#!/bin/bash

# Microservice Startup Script
# Start all microservices in virtual environment
# Supports multi-environment configuration: development, test, staging, production

# Default environment
ENVIRONMENT="development"

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Service list - Using two arrays for bash 3.2 compatibility
services_names=(
    "auth_service"
    "account_service"
    "session_service"
    "authorization_service"
    "audit_service"
    "storage_service"
    "notification_service"
    "payment_service"
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

services_ports=(
    8202
    8201
    8205
    8203
    8204
    8208
    8206
    8207
    8209
    8210
    8211
    8212
    8213
    8220
    8221
    8225
    8230
)

# PID file directory (relative to project root)
PID_DIR="./pids"
LOG_DIR="./logs"

# Function: Print colored messages
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function: Load environment configuration
load_environment() {
    local env=$1
    local env_folder
    local env_file

    # Validate environment name and map to deployment folder
    case $env in
        development|dev)
            env="development"
            env_folder="dev"
            env_file="deployment/dev/.env"
            ;;
        test|testing)
            env="test"
            env_folder="test"
            env_file="deployment/test/.env.test"
            ;;
        staging|stag)
            env="staging"
            env_folder="staging"
            env_file="deployment/staging/.env.staging"
            ;;
        production|prod)
            env="production"
            env_folder="production"
            env_file="deployment/production/.env.production"
            ;;
        *)
            print_message $RED "❌ Invalid environment: $env"
            print_message $YELLOW "Valid environments: development (dev), test, staging (stag), production (prod)"
            exit 1
            ;;
    esac

    # Check if environment file exists
    if [ ! -f "$env_file" ]; then
        print_message $RED "❌ Environment config file not found: $env_file"
        print_message $YELLOW "Please create config file: $env_file"
        exit 1
    fi

    # Set ENV environment variable
    export ENV=$env

    print_message $GREEN "✅ Environment config loaded: $env (file: $env_file)"
    print_message $BLUE "   ENV=$ENV"

    # Export environment variables (ConfigManager will auto-load)
    # No need to manually source .env file, ConfigManager handles it
}

# Function: Check virtual environment
check_venv() {
    if [[ "$VIRTUAL_ENV" == "" ]]; then
        print_message $YELLOW "⚠️  Virtual environment not detected, activating .venv ..."
        if [ -f "../../.venv/bin/activate" ]; then
            source ../../.venv/bin/activate
            print_message $GREEN "✅ Virtual environment activated"
        else
            print_message $RED "❌ Cannot find virtual environment ../../.venv/bin/activate"
            print_message $YELLOW "Please create virtual environment first: python -m venv .venv"
            exit 1
        fi
    else
        print_message $GREEN "✅ Already in virtual environment: $VIRTUAL_ENV"
    fi
}

# Function: Create necessary directories
setup_directories() {
    mkdir -p "$PID_DIR"
    mkdir -p "$LOG_DIR"
}

# Function: Stop all services
stop_all_services() {
    print_message $BLUE "\nStopping all services..."

    for i in "${!services_names[@]}"; do
        service=${services_names[$i]}
        port=${services_ports[$i]}
        pid_file="$PID_DIR/${service}.pid"

        if [ -f "$pid_file" ]; then
            pid=$(cat "$pid_file")
            if kill -0 $pid 2>/dev/null; then
                kill $pid
                print_message $YELLOW "  Stopped $service (PID: $pid)"
                rm "$pid_file"
            else
                rm "$pid_file"
            fi
        fi

        # Ensure port is released
        lsof -ti:$port | xargs kill -9 2>/dev/null
    done

    print_message $GREEN "✅ All services stopped\n"
}

# Function: Stop single service
stop_service() {
    local service=$1
    local port=$2
    local pid_file="$PID_DIR/${service}.pid"

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 $pid 2>/dev/null; then
            kill $pid
            print_message $YELLOW "  Stopped $service (PID: $pid)"
            rm "$pid_file"
        else
            rm "$pid_file"
        fi
    fi

    # Ensure port is released
    lsof -ti:$port | xargs kill -9 2>/dev/null
}

# Function: Start single service
start_service() {
    local service=$1
    local port=$2
    local reload=${3:-false}
    local pid_file="$PID_DIR/${service}.pid"
    local log_file="$LOG_DIR/${service}.log"

    # Check if port is already in use
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null ; then
        print_message $YELLOW "  ⚠️  Port $port is already in use, skipping $service"
        return 1
    fi

    # Start service
    if [ "$reload" = true ]; then
        print_message $BLUE "  Starting $service (Port: $port, Development mode - auto-reload)..."
        # Use uvicorn directly with auto-reload support
        nohup uvicorn microservices.${service}.main:app --host 0.0.0.0 --port $port --reload > "$log_file" 2>&1 &
    else
        print_message $BLUE "  Starting $service (Port: $port)..."
        # Use nohup to start service in background
        nohup python -m microservices.${service}.main > "$log_file" 2>&1 &
    fi

    local pid=$!

    # Save PID
    echo $pid > "$pid_file"

    # Wait for service to start
    sleep 3

    # Check if service started successfully
    if kill -0 $pid 2>/dev/null; then
        # Check health endpoint
        if curl -s http://localhost:$port/health >/dev/null 2>&1; then
            if [ "$reload" = true ]; then
                print_message $GREEN "  ✅ $service started successfully (PID: $pid, Development mode)"
            else
                print_message $GREEN "  ✅ $service started successfully (PID: $pid)"
            fi

            # Check Consul registration
            wait_for_consul_registration "$service" 10

            return 0
        else
            print_message $YELLOW "  ⚠️  $service started but health check failed (PID: $pid)"
            return 0
        fi
    else
        print_message $RED "  ❌ $service failed to start"
        rm "$pid_file"
        return 1
    fi
}

# Function: Check service status
check_service_status() {
    local service=$1
    local port=$2

    response=$(curl -s http://localhost:$port/health 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo "  ✅ $service: $response"
    else
        echo "  ❌ $service: Not responding"
    fi
}

# Function: Check Consul registration status
check_consul_registration() {
    local service=$1
    local consul_host=${2:-localhost}
    local consul_port=${3:-8500}

    # Query Consul API to check if service is registered
    local consul_url="http://${consul_host}:${consul_port}/v1/agent/services"
    local services_json=$(curl -s "$consul_url" 2>/dev/null)

    if [ $? -ne 0 ]; then
        return 1  # Consul unavailable
    fi

    # Check if service is in registered services list
    if echo "$services_json" | grep -q "\"${service}\""; then
        return 0  # Registered
    else
        return 2  # Not registered
    fi
}

# Function: Wait for Consul registration
wait_for_consul_registration() {
    local service=$1
    local max_attempts=${2:-10}
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        check_consul_registration "$service"
        local result=$?

        if [ $result -eq 0 ]; then
            print_message $GREEN "  ✅ $service successfully registered to Consul"
            return 0
        elif [ $result -eq 1 ]; then
            print_message $YELLOW "  ⚠️  Cannot connect to Consul"
            return 1
        fi

        attempt=$((attempt + 1))
        sleep 1
    done

    print_message $YELLOW "  ⚠️  $service not registered to Consul (timeout)"
    return 2
}

# Function: Show all service status
show_status() {
    print_message $BLUE "\n=== Service Status ==="

    for i in "${!services_names[@]}"; do
        service=${services_names[$i]}
        port=${services_ports[$i]}
        check_service_status $service $port

        # Check Consul registration status
        check_consul_registration "$service"
        local consul_status=$?
        if [ $consul_status -eq 0 ]; then
            echo "    🔗 Consul: Registered"
        elif [ $consul_status -eq 1 ]; then
            echo "    🔗 Consul: Cannot connect"
        else
            echo "    🔗 Consul: Not registered"
        fi
    done
}

# Function: Show logs
show_logs() {
    local service=$1
    if [ -z "$service" ]; then
        print_message $YELLOW "Please specify service name"
        print_message $BLUE "Available services: ${services_names[@]}"
    else
        log_file="$LOG_DIR/${service}.log"
        if [ -f "$log_file" ]; then
            tail -f "$log_file"
        else
            print_message $RED "Log file does not exist: $log_file"
        fi
    fi
}

# Main function
main() {
    # Parse arguments
    local action=""
    local env_param=""

    while [[ $# -gt 0 ]]; do
        case $1 in
            -e|--env)
                env_param="$2"
                shift 2
                ;;
            -*)
                print_message $RED "Unknown option: $1"
                exit 1
                ;;
            *)
                if [ -z "$action" ]; then
                    action="$1"
                    shift
                else
                    # Keep other arguments for later use
                    break
                fi
                ;;
        esac
    done

    # Set default action
    action=${action:-start}

    # Set environment
    if [ -n "$env_param" ]; then
        ENVIRONMENT="$env_param"
    fi

    # Load environment configuration
    load_environment "$ENVIRONMENT"

    case $action in
        start)
            print_message $BLUE "=== Starting all microservices (Environment: $ENVIRONMENT) ==="

            # Check virtual environment
            check_venv

            # Create directories
            setup_directories

            # Stop existing services
            stop_all_services

            # Start all services
            print_message $BLUE "Starting services..."
            local success_count=0
            local fail_count=0

            for i in "${!services_names[@]}"; do
                service=${services_names[$i]}
                port=${services_ports[$i]}
                if start_service $service $port false; then
                    ((success_count++))
                else
                    ((fail_count++))
                fi
            done

            # Show summary
            print_message $BLUE "\n=== Startup Complete ==="
            print_message $GREEN "Success: $success_count services"
            if [ $fail_count -gt 0 ]; then
                print_message $RED "Failed: $fail_count services"
            fi

            # Show status
            show_status

            print_message $BLUE "\nTips:"
            print_message $NC "  • View service status: ./scripts/start_user_service.sh status"
            print_message $NC "  • Stop all services: ./scripts/start_user_service.sh stop"
            print_message $NC "  • Restart all services: ./scripts/start_user_service.sh restart"
            print_message $NC "  • Restart specific service: ./scripts/start_user_service.sh restart <service_name>"
            print_message $NC "  • Start with different environment: ./scripts/start_user_service.sh --env test start"
            print_message $NC "  • Start in development mode: ./scripts/start_user_service.sh dev <service_name>"
            print_message $NC "  • View service logs: ./scripts/start_user_service.sh logs <service_name>"
            ;;
            
        stop)
            stop_all_services
            ;;
            
        restart)
            if [ -n "$2" ]; then
                # Restart specific service
                service_name=$2
                reload_mode=${3:-false}

                # Validate service name
                found=false
                service_port=""
                for i in "${!services_names[@]}"; do
                    if [ "${services_names[$i]}" = "$service_name" ]; then
                        found=true
                        service_port=${services_ports[$i]}
                        break
                    fi
                done

                if [ "$found" = false ]; then
                    print_message $RED "❌ Unknown service: $service_name"
                    print_message $BLUE "Available services: ${services_names[@]}"
                    exit 1
                fi

                print_message $BLUE "=== Restarting $service_name ==="
                stop_service $service_name $service_port
                sleep 2
                start_service $service_name $service_port $reload_mode
            else
                # Restart all services
                print_message $BLUE "=== Restarting all services ==="
                stop_all_services
                sleep 2
                $0 start
            fi
            ;;
            
        dev)
            if [ -n "$2" ]; then
                # Start specific service in development mode
                service_name=$2

                # Validate service name
                found=false
                service_port=""
                for i in "${!services_names[@]}"; do
                    if [ "${services_names[$i]}" = "$service_name" ]; then
                        found=true
                        service_port=${services_ports[$i]}
                        break
                    fi
                done

                if [ "$found" = false ]; then
                    print_message $RED "❌ Unknown service: $service_name"
                    print_message $BLUE "Available services: ${services_names[@]}"
                    exit 1
                fi

                print_message $BLUE "=== Starting $service_name in development mode ==="
                check_venv
                setup_directories
                stop_service $service_name $service_port
                sleep 1
                start_service $service_name $service_port true
            else
                print_message $RED "❌ Please specify service name"
                print_message $BLUE "Usage: $0 dev <service_name>"
                print_message $BLUE "Available services: ${services_names[@]}"
                exit 1
            fi
            ;;
            
        status)
            show_status
            ;;
            
        logs)
            show_logs $2
            ;;
            
        test)
            print_message $BLUE "=== Testing all service endpoints ==="

            for i in "${!services_names[@]}"; do
                service=${services_names[$i]}
                port=${services_ports[$i]}
                print_message $BLUE "\nTesting $service (Port: $port):"

                # Health check
                echo -n "  Health check: "
                curl -s http://localhost:$port/health | jq . 2>/dev/null || echo "Failed"

                # Test other endpoints (if available)
                echo -n "  API documentation: "
                curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/docs 2>/dev/null || echo "N/A"
                echo
            done
            ;;
            
        help|--help|-h)
            print_message $BLUE "Microservice Management Script"
            echo "Usage: $0 [options] [command] [arguments]"
            echo ""
            echo "Options:"
            echo "  -e, --env <env>          - Specify environment (development/dev, test, staging/stag, production/prod)"
            echo "                             Default: development"
            echo ""
            echo "Commands:"
            echo "  start                    - Start all services (default)"
            echo "  stop                     - Stop all services"
            echo "  restart                  - Restart all services"
            echo "  restart <service>        - Restart specific service"
            echo "  dev <service>            - Start specific service in development mode (with auto-reload)"
            echo "  status                   - Show service status"
            echo "  logs <service>           - View service logs"
            echo "  test                     - Test all service endpoints"
            echo "  help                     - Show this help message"
            echo ""
            echo "Environment configuration files:"
            echo "  development              - .env.development (default)"
            echo "  test                     - .env.test"
            echo "  staging                  - .env.staging"
            echo "  production               - .env.production"
            echo ""
            echo "Examples:"
            echo "  $0 start                             # Start with default environment (development)"
            echo "  $0 --env prod start                  # Start with production environment"
            echo "  $0 -e test restart task_service      # Restart task service with test environment"
            echo "  $0 --env staging dev task_service    # Start in development mode with staging environment"
            echo "  $0 logs task_service                 # View task service logs"
            echo ""
            echo "Service list:"
            for i in "${!services_names[@]}"; do
                echo "  - ${services_names[$i]} (Port: ${services_ports[$i]})"
            done
            ;;
            
        *)
            print_message $RED "Unknown command: $action"
            echo "Use $0 help to view help"
            exit 1
            ;;
    esac
}

# Capture exit signals to ensure cleanup
trap 'print_message $YELLOW "\nInterrupt signal received, cleaning up..."; stop_all_services; exit 1' INT TERM

# Run main function
main "$@"