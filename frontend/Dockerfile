# Stage 1: Build
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# Production-Build ohne VITE_API_URL = same-origin (API via nginx reverse proxy)
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL

COPY . .
# check:locales + typecheck (vue-tsc) + vite build — Typfehler brechen den Image-Build ab
RUN npm run build

# Stage 2: Serve
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
# Vertrauenswürdige Proxies für X-Forwarded-For: Snippet wird beim Start aus
# TRUSTED_PROXY_CIDRS neu geschrieben; der Default hier gilt z. B. für `nginx -t` im Build
ENV TRUSTED_PROXY_CIDRS=172.16.0.0/12
COPY nginx/30-casa-real-ip.sh /docker-entrypoint.d/30-casa-real-ip.sh
# CRLF entfernen (Checkout unter Windows) und ausführbar machen — sonst überspringt das Image das Skript
RUN sed -i 's/\r$//' /docker-entrypoint.d/30-casa-real-ip.sh \
    && chmod 755 /docker-entrypoint.d/30-casa-real-ip.sh \
    && printf 'set_real_ip_from 172.16.0.0/12;\n' > /etc/nginx/snippets/real-ip.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
