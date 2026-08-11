FROM debian:bookworm-slim AS wal-g

ARG TARGETARCH
ARG WAL_G_VERSION=v3.0.8
ARG WAL_G_AMD64_SHA256=b0df1b484035eb5f131db7bbd303d1a460391848fdcce34ba1e0a564cca493e9
ARG WAL_G_ARM64_SHA256=048b5033c34c1487dc1fccc0572db030e323230984ccc093e80e4e4081c797d1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && detected_arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && case "${detected_arch}" in \
        amd64) asset_arch="amd64"; checksum="${WAL_G_AMD64_SHA256}" ;; \
        arm64|aarch64) asset_arch="aarch64"; checksum="${WAL_G_ARM64_SHA256}" ;; \
        *) echo "Unsupported architecture: ${detected_arch}" >&2; exit 1 ;; \
    esac \
    && asset="wal-g-pg-22.04-${asset_arch}.tar.gz" \
    && curl --fail --location --show-error --silent \
        "https://github.com/wal-g/wal-g/releases/download/${WAL_G_VERSION}/${asset}" \
        --output "/tmp/${asset}" \
    && echo "${checksum}  /tmp/${asset}" | sha256sum --check --strict \
    && tar --extract --gzip --file "/tmp/${asset}" --directory /tmp \
    && mv "/tmp/wal-g-pg-22.04-${asset_arch}" /usr/local/bin/wal-g \
    && chmod 0755 /usr/local/bin/wal-g

FROM postgres:17.6-bookworm

RUN apt-get update \
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
