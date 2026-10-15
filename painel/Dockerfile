# Constrói o painel e gera a imagem do Caddy que serve o painel e faz proxy da API.
# Contexto de build: raiz do repositório (veja docker-compose.yml).
FROM node:22-alpine AS build
WORKDIR /painel
COPY painel/package.json painel/package-lock.json ./
RUN npm ci
COPY painel/ ./
RUN npm run build

FROM caddy:2.8
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /painel/dist /srv/painel
