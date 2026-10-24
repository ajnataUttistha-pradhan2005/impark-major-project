#!/usr/bin/env bash
# ==============================================================================
# IMPARK Evaluator & Observability Pipeline - Cloud EC2 Migration & Deployment
# Self-hosted, decoupled LangGraph evaluation stack (Redis, Postgres, Grafana, CPU Daemon)
# ==============================================================================

set -euo pipefail

# ANSI Color Codes
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}=====================================================================${NC}"
echo -e "${CYAN}       IMPARK Evaluator Pipeline - AWS EC2 Cloud Deployment         ${NC}"
echo -e "${CYAN}=====================================================================${NC}"

# 1. Determine Working Directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
echo -e "${GREEN}[+] Working Directory:${NC} $SCRIPT_DIR"

# 2. Check Architecture & Privileges
ARCH=$(uname -m)
echo -e "${GREEN}[+] System Architecture:${NC} $ARCH"
if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
else
    SUDO=""
fi

# 3. Detect Linux Distribution & Install Docker if Missing
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}[!] Docker not found. Installing Docker engine...${NC}"
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO=$ID
    else
        DISTRO="unknown"
    fi

    if [[ "$DISTRO" == "ubuntu" || "$DISTRO" == "debian" ]]; then
        $SUDO apt-get update -y
        $SUDO apt-get install -y ca-certificates curl gnupg lsb-release
        $SUDO install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/$DISTRO/gpg | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
        $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$DISTRO $(lsb_release -cs) stable" | $SUDO tee /etc/apt/sources.list.d/docker.list > /dev/null
        $SUDO apt-get update -y
        $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    elif [[ "$DISTRO" == "amzn" || "$DISTRO" == "fedora" || "$DISTRO" == "rhel" || "$DISTRO" == "centos" ]]; then
        if [[ "$DISTRO" == "amzn" ]]; then
            $SUDO dnf install -y docker libxcrypt-compat
            $SUDO systemctl enable --now docker
            # Install compose plugin for AL2023
            DOCKER_CONFIG=${DOCKER_CONFIG:-/usr/local/lib/docker}
            $SUDO mkdir -p $DOCKER_CONFIG/cli-plugins
            $SUDO curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$ARCH -o $DOCKER_CONFIG/cli-plugins/docker-compose
            $SUDO chmod +x $DOCKER_CONFIG/cli-plugins/docker-compose
        else
            $SUDO dnf install -y dnf-plugins-core
            $SUDO dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
            $SUDO dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
            $SUDO systemctl enable --now docker
        fi
    fi

    # Enable and start Docker service
    $SUDO systemctl enable docker || true
    $SUDO systemctl start docker || true

    # Add current user to docker group if running under non-root
    if [ -n "${SUDO_USER:-}" ]; then
        $SUDO usermod -aG docker "$SUDO_USER"
        echo -e "${GREEN}[+] Added $SUDO_USER to docker group.${NC}"
    elif [ "$EUID" -ne 0 ]; then
        $SUDO usermod -aG docker "$USER"
        echo -e "${GREEN}[+] Added $USER to docker group.${NC}"
    fi
fi

# Resolve Docker Compose command
if docker compose version &> /dev/null; then
    COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE="docker-compose"
else
    echo -e "${RED}[ERROR] Neither 'docker compose' nor 'docker-compose' found.${NC}"
    exit 1
fi

echo -e "${GREEN}[+] Docker Engine:${NC} $(docker --version)"
echo -e "${GREEN}[+] Docker Compose:${NC} $($COMPOSE version)"

# 4. Kernel Tuning for High-Performance Redis & Zero-Drop Sockets
echo -e "${CYAN}[*] Applying Linux kernel memory optimizations for Redis...${NC}"
$SUDO sysctl -w vm.overcommit_memory=1 > /dev/null || true
if [ -f /sys/kernel/mm/transparent_hugepage/enabled ]; then
    echo never | $SUDO tee /sys/kernel/mm/transparent_hugepage/enabled > /dev/null || true
fi

# 5. Launch Infrastructure via Docker Compose
echo -e "${CYAN}[*] Starting Redis, PostgreSQL, Grafana, and Evaluator Worker containers...${NC}"
$COMPOSE down --remove-orphans || true
$COMPOSE --profile all up -d --build

# 6. Healthcheck Verification Wait Loop
echo -e "${CYAN}[*] Waiting for services to reach healthy state...${NC}"
MAX_WAIT=60
COUNTER=0

while [ $COUNTER -lt $MAX_WAIT ]; do
    REDIS_STATUS=$(docker inspect --format='{{json .State.Health.Status}}' eval-redis 2>/dev/null || echo '"unknown"')
    PG_STATUS=$(docker inspect --format='{{json .State.Health.Status}}' eval-postgres 2>/dev/null || echo '"unknown"')

    if [[ "$REDIS_STATUS" == *"healthy"* && "$PG_STATUS" == *"healthy"* ]]; then
        echo -e "${GREEN}[+] Redis and PostgreSQL are HEALTHY!${NC}"
        break
    fi

    echo -ne "  Waiting for databases (Redis: $REDIS_STATUS, Postgres: $PG_STATUS)... [$COUNTER/${MAX_WAIT}s]\r"
    sleep 3
    COUNTER=$((COUNTER + 3))
done

if [ $COUNTER -ge $MAX_WAIT ]; then
    echo -e "\n${YELLOW}[!] Warning: Services did not report healthy within ${MAX_WAIT}s. Inspecting container logs...${NC}"
    docker logs eval-postgres --tail 20 || true
    docker logs eval-redis --tail 20 || true
fi

# 7. Run Verification Test Suite Inside the Environment
echo -e "${CYAN}[*] Executing Verification Test Suite (Flow 1 & Flow 2)...${NC}"
if docker ps --format '{{.Names}}' | grep -q 'eval-worker'; then
    echo -e "${GREEN}[+] Testing pipeline via running container 'eval-worker'...${NC}"
    docker exec eval-worker python test_pipeline.py
else
    echo -e "${YELLOW}[!] Container worker not detected. Testing via local python if available...${NC}"
    if command -v python3 &> /dev/null; then
        REQUIRE_LIVE_INFRA=1 python3 test_pipeline.py
    fi
fi

# 8. Detect Public EC2 IP Address for User Access
PUBLIC_IP=$(curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || curl -s --connect-timeout 2 https://ifconfig.me 2>/dev/null || echo "YOUR-EC2-IP")
POSTGRES_PORT_DISPLAY=${EVAL_POSTGRES_PORT:-5433}

echo -e "\n${GREEN}=====================================================================${NC}"
echo -e "${GREEN}       DEPLOYMENT SUCCESSFUL! IMPARK EVALUATOR IS ACTIVE           ${NC}"
echo -e "${GREEN}=====================================================================${NC}"
echo -e "  • Grafana Dashboard:    ${CYAN}http://${PUBLIC_IP}:3000${NC}"
echo -e "  • Default Login:        Username: ${YELLOW}admin${NC} | Password: ${YELLOW}admin${NC}"
echo -e "  • Pre-Loaded Dashboard: ${CYAN}http://${PUBLIC_IP}:3000/d/impark-eval-overview${NC}"
echo -e "  • PostgreSQL Port:      ${CYAN}localhost:${POSTGRES_PORT_DISPLAY}${NC} (db: eval_db, user: postgres)"
echo -e "  • Redis Stream Broker:  ${CYAN}localhost:6379${NC} (stream: agent-logs)"
echo -e "\n${YELLOW}[NOTE for EC2 Security Groups]:${NC}"
echo -e "  Ensure your EC2 Security Group permits Inbound Traffic on Port 3000 (TCP)"
echo -e "  to allow access to the Grafana evaluation dashboard from your web browser."
echo -e "${GREEN}=====================================================================${NC}\n"
