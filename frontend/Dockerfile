FROM node:22.22.0-alpine AS build

WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:1.31.8-alpine-slim@sha256:9c68ad4f28e7dee4b9484a7859bf451da39ef661bcd038ef62e87593fcd91c86
RUN apk add --no-cache --upgrade libcrypto3 libssl3 \
    'musl>=1.2.6-r3' 'musl-utils>=1.2.6-r3' 'pcre2>=10.49-r0' 'zlib>=1.4-r0'
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
