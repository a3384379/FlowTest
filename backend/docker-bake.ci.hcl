// CI builds the unique Compose image targets once, then loads every service tag.
// Cache scopes are separated by Dockerfile target and platform. BuildKit still
// validates Dockerfile, lockfile, patch, and source inputs within each scope.
variable "FLOWTEST_CI_SHA" {
  default = "local"
}

variable "FLOWTEST_PR_HEAD_SHA" {
  default = "local"
}

target "_ci_common" {
  platforms = ["linux/amd64"]
  labels = {
    "org.opencontainers.image.revision" = FLOWTEST_CI_SHA
    "com.flowtest.pr-head"             = FLOWTEST_PR_HEAD_SHA
  }
}

target "backend" {
  inherits   = ["_ci_common"]
  tags       = ["flowtest-backend", "flowtest-backend:ci", "flowtest-worker", "flowtest-worker-data", "flowtest-worker-ai", "flowtest-beat"]
  cache-from = ["type=gha,scope=flowtest-backend-app-linux-amd64"]
  cache-to   = ["type=gha,scope=flowtest-backend-app-linux-amd64,mode=max,ignore-error=true"]
}

target "frontend" {
  inherits   = ["_ci_common"]
  tags       = ["flowtest-frontend", "flowtest-frontend:ci"]
  cache-from = ["type=gha,scope=flowtest-frontend-linux-amd64"]
  cache-to   = ["type=gha,scope=flowtest-frontend-linux-amd64,mode=max,ignore-error=true"]
}

target "worker-performance" {
  inherits   = ["_ci_common"]
  tags       = ["flowtest-worker-performance", "flowtest-performance:ci"]
  cache-from = ["type=gha,scope=flowtest-performance-linux-amd64"]
  cache-to   = ["type=gha,scope=flowtest-performance-linux-amd64,mode=max,ignore-error=true"]
}

target "worker-environment" {
  inherits   = ["_ci_common"]
  tags       = ["flowtest-worker-environment", "flowtest-environment:ci"]
  cache-from = ["type=gha,scope=flowtest-environment-linux-amd64"]
  cache-to   = ["type=gha,scope=flowtest-environment-linux-amd64,mode=max,ignore-error=true"]
}

target "environment-docker" {
  inherits   = ["_ci_common"]
  tags       = ["flowtest-environment-docker", "flowtest-environment-daemon:ci"]
  cache-from = ["type=gha,scope=flowtest-environment-daemon-linux-amd64"]
  cache-to   = ["type=gha,scope=flowtest-environment-daemon-linux-amd64,mode=max,ignore-error=true"]
}

target "runner-agent-a" {
  inherits   = ["_ci_common"]
  tags       = ["flowtest-runner-agent-a", "flowtest-runner-agent-b", "flowtest-runner:ci"]
  cache-from = ["type=gha,scope=flowtest-runner-linux-amd64"]
  cache-to   = ["type=gha,scope=flowtest-runner-linux-amd64,mode=max,ignore-error=true"]
}

target "mock-target" {
  inherits   = ["_ci_common"]
  tags       = ["flowtest-mock-target", "flowtest-grpc-target", "flowtest-mock-target:ci"]
  cache-from = ["type=gha,scope=flowtest-mock-target-linux-amd64"]
  cache-to   = ["type=gha,scope=flowtest-mock-target-linux-amd64,mode=max,ignore-error=true"]
}

target "postgres" {
  inherits   = ["_ci_common"]
  cache-from = ["type=gha,scope=flowtest-postgres-walg-linux-amd64"]
  cache-to   = ["type=gha,scope=flowtest-postgres-walg-linux-amd64,mode=max,ignore-error=true"]
}

group "ci-security" {
  targets = ["backend", "frontend", "worker-performance", "worker-environment", "environment-docker", "runner-agent-a", "mock-target"]
}

group "ci-compose" {
  targets = ["backend", "frontend", "worker-performance", "worker-environment", "environment-docker", "mock-target", "postgres"]
}
