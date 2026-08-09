FROM ghcr.io/astral-sh/uv:0.11.32 AS uv
FROM debian:trixie-slim AS python-runtime

ENV PATH="/usr/local/bin:$PATH" \
    PYTHON_VERSION="3.13.15" \
    PYTHON_SHA256="1e66a7945a48390ee4c2a4268a0e4185884059a13c4aab6d148aa208deea4a76"

# Keep this bootstrap identical to backend/Dockerfile so BuildKit shares the
# layers until the official Python 3.13.15 slim image is published.
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
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
