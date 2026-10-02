# syntax=docker/dockerfile:1

# ---- Build: compile the static bundle -----------------------------------------
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ---- Serve: static files + reverse proxy, as a non-root user ------------------
FROM nginxinc/nginx-unprivileged:1.30-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

# The base image already runs as the unprivileged "nginx" user (uid 101).
USER 101
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/nginx-health || exit 1
