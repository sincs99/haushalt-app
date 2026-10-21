# Stage 1: Build
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# Production-Build ohne VITE_API_URL = same-origin (API via nginx reverse proxy)
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL

COPY . .
RUN npm run check:locales && npx vite build

# Stage 2: Serve
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf

# Nur den benannten Proxy vertrauen; alle nginx-eigenen $Variablen erhalten.
ENV NPM_TRUSTED_PROXY_IP=127.0.0.1
ENV NGINX_ENVSUBST_FILTER=^NPM_TRUSTED_PROXY_IP$

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
