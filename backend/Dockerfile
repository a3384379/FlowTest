FROM ghcr.io/astral-sh/uv:0.11.32 AS uv
FROM golang:1.26.6-alpine3.23@sha256:5978cc992ad5ef96a7469713c8af849c1433824761ce3be2c56381403cd8d9a3 AS go-toolchain

RUN apk add --no-cache git make
ENV GOTOOLCHAIN=local

FROM go-toolchain AS k6-builder
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    set -eux; \
    GOBIN=/out CGO_ENABLED=0 go install go.k6.io/k6/v2@v2.2.0; \
    go version -m /out/k6 | grep -F 'go1.26.6'; \
    /out/k6 version | grep -F 'k6 v2.2.0'

FROM go-toolchain AS docker-cli-builder
WORKDIR /go/src/github.com/docker/cli
RUN --mount=type=cache,target=/root/.cache/go-build \
    set -eux; \
    git init; \
    git remote add origin https://github.com/docker/cli.git; \
    git fetch --depth 1 origin a7dcaa6fdb6ed04aacbfdc76357fdae01605609e; \
    git checkout --detach FETCH_HEAD; \
    test "$(git rev-parse HEAD)" = a7dcaa6fdb6ed04aacbfdc76357fdae01605609e; \
    SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)" \
        VERSION=29.7.2 \
        GITCOMMIT=a7dcaa6fdb6ed04aacbfdc76357fdae01605609e \
        CGO_ENABLED=0 \
        GO_STRIP=1 \
        ./scripts/build/binary; \
    install -D build/docker /out/docker; \
    go version -m /out/docker | grep -F 'go1.26.6'; \
    /out/docker --version | grep -F 'Docker version 29.7.2'

FROM go-toolchain AS dockerd-builder
RUN apk add --no-cache bash build-base libseccomp-dev libseccomp-static linux-headers pkgconf
WORKDIR /src/moby
RUN --mount=type=cache,target=/root/.cache/go-build \
    set -eux; \
    git init; \
    git remote add origin https://github.com/moby/moby.git; \
    git fetch --depth 1 origin 6a43e3d5afddf4111da0f864bbc7cae5d7e95001; \
    git checkout --detach FETCH_HEAD; \
    test "$(git rev-parse HEAD)" = 6a43e3d5afddf4111da0f864bbc7cae5d7e95001; \
    SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)" \
        VERSION=29.7.2 \
        DOCKER_GITCOMMIT=6a43e3d5afddf4111da0f864bbc7cae5d7e95001 \
        DOCKER_STATIC=1 \
        BUILDFLAGS=-buildvcs=false \
        PREFIX=/out \
        ./hack/make.sh binary-daemon; \
    go version -m /out/bundles/binary-daemon/dockerd | grep -F 'go1.26.6'; \
    /out/bundles/binary-daemon/dockerd --version | grep -F 'Docker version 29.7.2'

FROM go-toolchain AS containerd-builder
WORKDIR /src/containerd
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    set -eux; \
    git init; \
    git remote add origin https://github.com/containerd/containerd.git; \
    git fetch --depth 1 origin aad11006b869517fcd3009450b6f82da282e1a9b; \
    git checkout --detach FETCH_HEAD; \
    test "$(git rev-parse HEAD)" = aad11006b869517fcd3009450b6f82da282e1a9b; \
    git tag v2.3.3; \
    go get golang.org/x/text@v0.39.0 google.golang.org/grpc@v1.82.1; \
    go mod vendor; \
    make \
        VERSION=v2.3.3 \
        REVISION=aad11006b869517fcd3009450b6f82da282e1a9b \
        bin/containerd bin/ctr

FROM docker:29.7.2-dind@sha256:12e683a161823b2a839aeea999b9d960e6e1f9a97b1679ad6b441982e2d9cf07 AS environment-daemon
COPY --from=docker-cli-builder /out/docker /usr/local/bin/docker
COPY --from=dockerd-builder /out/bundles/binary-daemon/dockerd /usr/local/bin/dockerd
COPY --from=containerd-builder /src/containerd/bin/containerd /usr/local/bin/containerd
COPY --from=containerd-builder /src/containerd/bin/ctr /usr/local/bin/ctr
RUN set -eux; \
    rm -f \
        /usr/local/libexec/docker/cli-plugins/docker-buildx \
        /usr/local/libexec/docker/cli-plugins/docker-compose; \
    containerd --version; \
    ctr --version

FROM debian:trixie-slim AS python-runtime

ENV PATH="/usr/local/bin:$PATH" \
    PYTHON_VERSION="3.13.15" \
    PYTHON_SHA256="1e66a7945a48390ee4c2a4268a0e4185884059a13c4aab6d148aa208deea4a76"

# Docker Hub had not published the 3.13.15 slim tag when S12 was cut. Build the
# signed CPython release using the same inputs as the official Docker image.
RUN set -eux; \
    saved_apt_mark="$(apt-mark showmanual)"; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        dpkg-dev \
        gcc \
        gnupg \
        libbluetooth-dev \
        libbz2-dev \
        libc6-dev \
        libdb-dev \
        libffi-dev \
        libgdbm-dev \
        liblzma-dev \
        libncursesw5-dev \
        libreadline-dev \
        libsqlite3-dev \
        libssl-dev \
        make \
        netbase \
        tk-dev \
        tzdata \
        uuid-dev \
        wget \
        xz-utils \
        zlib1g-dev; \
    wget -O python.tar.xz \
        "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz"; \
    echo "${PYTHON_SHA256} *python.tar.xz" | sha256sum -c -; \
    wget -O python.tar.xz.asc \
        "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz.asc"; \
    export GNUPGHOME="$(mktemp -d)"; \
    gpg --batch --keyserver hkps://keys.openpgp.org \
        --recv-keys 7169605F62C751356D054A26A821E680E5FA6305; \
    gpg --batch --verify python.tar.xz.asc python.tar.xz; \
    gpgconf --kill all; \
    rm -rf "${GNUPGHOME}" python.tar.xz.asc; \
    mkdir -p /usr/src/python; \
    tar --extract --directory /usr/src/python --strip-components=1 --file python.tar.xz; \
    rm python.tar.xz; \
    cd /usr/src/python; \
    build_arch="$(dpkg-architecture --query DEB_BUILD_GNU_TYPE)"; \
    ./configure \
        --build="${build_arch}" \
        --enable-loadable-sqlite-extensions \
        --enable-optimizations \
        --enable-option-checking=fatal \
        --enable-shared \
        --with-ensurepip; \
    make -j "$(nproc)"; \
    make install; \
    cd /; \
    rm -rf /usr/src/python; \
    find /usr/local -depth \
        \( \
            \( -type d -a \( -name test -o -name tests -o -name idle_test \) \) \
            -o \( -type f -a \( -name '*.pyc' -o -name '*.pyo' -o -name 'libpython*.a' \) \) \
        \) -exec rm -rf '{}' +; \
    ldconfig; \
    apt-mark auto '.*' > /dev/null; \
    if test -n "${saved_apt_mark}"; then apt-mark manual ${saved_apt_mark}; fi; \
    find /usr/local -type f -executable -not -name '*tkinter*' -exec ldd '{}' ';' \
        | awk '/=>/ { so = $(NF-1); if (index(so, "/usr/local/") == 1) { next }; gsub("^/(usr/)?", "", so); printf "*%s\n", so }' \
        | sort -u \
        | xargs -rt dpkg-query --search \
        | awk 'sub(":$", "", $1) { print $1 }' \
        | sort -u \
        | xargs -r apt-mark manual; \
    apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false; \
    apt-get dist-clean; \
    python3 --version; \
    pip3 --version

RUN set -eux; \
    for source_name in idle3 pip3 pydoc3 python3 python3-config; do \
        target_name="$(echo "${source_name}" | tr -d 3)"; \
        test -s "/usr/local/bin/${source_name}"; \
        test ! -e "/usr/local/bin/${target_name}"; \
        ln -s "${source_name}" "/usr/local/bin/${target_name}"; \
    done

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

FROM python-runtime AS performance-runtime
COPY --from=k6-builder /out/k6 /usr/local/bin/k6
RUN set -eux; \
    groupadd --gid 65532 flowtest; \
    useradd --uid 65532 --gid 65532 --no-create-home --home-dir /tmp \
        --shell /usr/sbin/nologin flowtest; \
    k6 version | grep -F 'k6 v2.2.0'
ENV HOME=/tmp
USER flowtest

FROM python-runtime AS environment-runtime
COPY --from=docker-cli-builder /out/docker /usr/local/bin/docker
RUN set -eux; \
    groupadd --gid 65532 flowtest; \
    useradd --uid 65532 --gid 65532 --no-create-home --home-dir /tmp \
        --shell /usr/sbin/nologin flowtest; \
    docker --version
ENV HOME=/tmp
USER flowtest

FROM python-runtime AS runner-runtime
RUN set -eux; \
    groupadd --gid 65532 flowtest; \
    useradd --uid 65532 --gid 65532 --no-create-home --home-dir /tmp \
        --shell /usr/sbin/nologin flowtest; \
    install --directory --owner=65532 --group=65532 --mode=0700 /var/lib/flowtest-runner
ENV HOME=/tmp
USER flowtest
ENTRYPOINT ["python", "-m", "app.runner.agent"]

FROM python-runtime AS application-runtime
