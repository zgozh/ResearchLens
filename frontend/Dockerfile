# ---- frontend build (Next.js standalone) ----
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --legacy-peer-deps || npm install

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# The browser (user's machine) reaches the backend via the published host port.
ARG NEXT_PUBLIC_API_URL=http://localhost:8002
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# 默认 0 = 走真实 canonical API（后端已实现 §5.12 并端到端验证）。
# 设 1 才切静态 fixtures（离线开发用）。构建期必须注入，否则客户端 bundle 读不到。
ARG NEXT_PUBLIC_USE_FIXTURES=0
ENV NEXT_PUBLIC_USE_FIXTURES=$NEXT_PUBLIC_USE_FIXTURES
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
ENV PORT=3000
CMD ["node", "server.js"]
