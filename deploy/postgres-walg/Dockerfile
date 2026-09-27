# syntax=docker/dockerfile:1.7

# WAL-G v3.0.9 release binaries contain fixable Go vulnerabilities. Rebuild the
# pinned release source with patched Go dependencies until upstream ships them.
FROM golang:1.27.0-bookworm@sha256:ded31c68586d2e49e760acc2e65a884b23d032e9bbbed0ae0c55abd3fcaf4452 AS wal-g

ARG WAL_G_COMMIT=3e493188db28335fb93a45bd680c6ff8fc3028c1

RUN git clone --depth 1 --branch v3.0.9 --single-branch https://github.com/wal-g/wal-g.git /src \
    && test "$(git -C /src rev-parse HEAD)" = "${WAL_G_COMMIT}"

WORKDIR /src
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go mod edit -go=1.27.0 \
        -require=golang.org/x/crypto@v0.57.0 \
        -require=google.golang.org/grpc@v1.83.2 \
    && go mod tidy \
    && CGO_ENABLED=0 go build -mod=readonly -trimpath \
        -ldflags "-s -w -X github.com/wal-g/wal-g/cmd/pg.walgVersion=v3.0.9-patched -X github.com/wal-g/wal-g/cmd/pg.gitRevision=${WAL_G_COMMIT}" \
        -o /usr/local/bin/wal-g ./main/pg

FROM postgres:17.11-bookworm@sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652

RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        libbrotli1 \
        liblzo2-2 \
        libsodium23 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=wal-g /usr/local/bin/wal-g /usr/local/bin/wal-g
COPY entrypoint.sh /usr/local/bin/flowtest-postgres-entrypoint

ENTRYPOINT ["flowtest-postgres-entrypoint"]
CMD ["postgres"]
