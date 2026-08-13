FROM nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236

COPY nginx.conf /etc/nginx/nginx.conf
COPY snippets /etc/nginx/snippets

# 构建期把服务名临时改为回环地址执行 nginx -t，再恢复生产配置。
RUN set -eux; \
    cp /etc/nginx/nginx.conf /tmp/nginx.conf; \
    cp /etc/nginx/snippets/common-server.conf /tmp/common-server.conf; \
    sed -i \
      -e 's/server backend:8000/server 127.0.0.1:8000/' \
      -e 's/server frontend:80/server 127.0.0.1:8080/' \
      /etc/nginx/nginx.conf; \
    sed -i 's/minio:9000/127.0.0.1:9000/g' /etc/nginx/snippets/common-server.conf; \
    nginx -t; \
    mv /tmp/nginx.conf /etc/nginx/nginx.conf; \
    mv /tmp/common-server.conf /etc/nginx/snippets/common-server.conf
