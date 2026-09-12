# Stage 1: Build static assets using Node 20
FROM docker.io/library/node:20-alpine AS builder

WORKDIR /app

# 1. Copy ONLY package manifest files first for strict npm layer caching
COPY package.json package-lock.json ./

# 2. Clean install npm dependencies (cached unless package files change)
RUN npm ci

# 3. Copy frontend source code (code edits will NOT re-trigger npm ci)
COPY . .

# 4. Build Vite production bundle
RUN npm run build

# Stage 2: Production static web server using Nginx
FROM docker.io/library/nginx:alpine

# Copy Nginx server configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy compiled static assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
