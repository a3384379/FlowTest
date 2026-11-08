# syntax=docker/dockerfile:1.7

# WAL-G v3.0.9 release binaries contain fixable Go vulnerabilities. Rebuild the
# pinned release source with patched Go dependencies until upstream ships them.
FROM golang:1.27.2-bookworm@sha256:5cf287a799e6b94384bad13d16b14904c531f51ba65792237e122ce42b392f61 AS wal-g

ARG WAL_G_COMMIT=3e493188db28335fb93a45bd680c6ff8fc3028c1

RUN git clone --depth 1 --branch v3.0.9 --single-branch https://github.com/wal-g/wal-g.git /src \
    && test "$(git -C /src rev-parse HEAD)" = "${WAL_G_COMMIT}"

WORKDIR /src
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go mod edit -go=1.27.2 \
        -require=github.com/go-jose/go-jose/v4@v4.1.6 \
        -require=github.com/klauspost/compress@v1.20.2 \
        -require=golang.org/x/crypto@v0.58.0 \
        -require=golang.org/x/net@v0.62.0 \
        -require=google.golang.org/grpc@v1.83.2 \
    && go mod tidy \
    && CGO_ENABLED=0 go build -mod=readonly -trimpath \
        -ldflags "-s -w -X github.com/wal-g/wal-g/cmd/pg.walgVersion=v3.0.9-patched -X github.com/wal-g/wal-g/cmd/pg.gitRevision=${WAL_G_COMMIT}" \
        -o /usr/local/bin/wal-g ./main/pg

FROM postgres:17.11-bookworm@sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652

RUN set -eux; \
    apt-get update; \
    apt-get upgrade --yes --no-install-recommends; \
    apt-get install --yes --no-install-recommends \
        ca-certificates \
        libbrotli1 \
        liblzo2-2 \
        libsodium23; \
    for package in \
        'apt=2.6.2' 'libapt-pkg6.0=2.6.2' \
        'libbrotli1=1.0.9-2+deb12u1' \
        'libpcre2-8-0=10.42-1+deb12u2' \
        'libsasl2-2=2.1.28+dfsg-10+deb12u1' 'libsasl2-modules-db=2.1.28+dfsg-10+deb12u1' \
        'libssl3=3.0.22-1~deb12u2' 'openssl=3.0.22-1~deb12u2' \
        'perl-base=5.36.0-7+deb12u4'; do \
        installed_version="$(dpkg-query --show --showformat='${Version}' "${package%%=*}")"; \
        dpkg --compare-versions "$installed_version" ge "${package#*=}"; \
    done; \
    rm -rf /var/lib/apt/lists/*

COPY --from=wal-g /usr/local/bin/wal-g /usr/local/bin/wal-g
COPY entrypoint.sh /usr/local/bin/flowtest-postgres-entrypoint

ENTRYPOINT ["flowtest-postgres-entrypoint"]
CMD ["postgres"]
