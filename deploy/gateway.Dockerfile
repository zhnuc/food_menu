# Optional private development gateway. Credentials are mounted, never baked in.
FROM node:22-bookworm-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund \
    && useradd --uid 10002 --create-home gateway
COPY src ./src
COPY static ./static
RUN mkdir /app/logs && chown gateway:gateway /app/logs
USER gateway
CMD ["node", "src/services/api-server.js", "--no-ui"]
