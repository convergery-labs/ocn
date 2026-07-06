# Stage 1 - build
FROM node:20-alpine AS build
ARG VITE_API_BASE_URL=http://localhost:8007
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2 - serve
FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
