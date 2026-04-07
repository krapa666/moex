FROM alpine:3.20 AS assets

WORKDIR /assets
COPY index.html app.js styles.css ./
COPY nginx.conf /tmp/nginx.conf


FROM nginx:1.27-alpine AS runtime

COPY --from=assets /assets/index.html /usr/share/nginx/html/index.html
COPY --from=assets /assets/app.js /usr/share/nginx/html/app.js
COPY --from=assets /assets/styles.css /usr/share/nginx/html/styles.css
COPY --from=assets /tmp/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
