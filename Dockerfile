FROM node:20-alpine AS build
WORKDIR /app
ARG VITE_AUTH0_DOMAIN
ARG VITE_AUTH0_CLIENT_ID
ARG VITE_GOOGLE_MAPS_KEY
ARG VITE_NOETL_API_BASE_URL
ENV VITE_AUTH0_DOMAIN=${VITE_AUTH0_DOMAIN}
ENV VITE_AUTH0_CLIENT_ID=${VITE_AUTH0_CLIENT_ID}
ENV VITE_GOOGLE_MAPS_KEY=${VITE_GOOGLE_MAPS_KEY}
ENV VITE_NOETL_API_BASE_URL=${VITE_NOETL_API_BASE_URL}
COPY package*.json ./
RUN npm ci
COPY . ./
RUN npm run build

FROM nginx:1.27-alpine
LABEL org.opencontainers.image.title="Muno"       org.opencontainers.image.description="Adiona/travel trip-planner web app"       org.opencontainers.image.source="https://github.com/noetl/travel"       org.opencontainers.image.licenses="Apache-2.0"
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
