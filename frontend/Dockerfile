FROM alpine:3.20 AS assets

WORKDIR /assets
COPY index.html app.js security-details.js security-keyboard.js copy-link.js theme.js styles.css shell.css forecast.css theme.css ./
COPY volumes ./volumes
COPY dashboard ./dashboard
COPY watchlist ./watchlist
COPY analytics ./analytics
COPY nginx.conf /tmp/nginx.conf


FROM nginx:1.27-alpine AS runtime

COPY --from=assets /assets/index.html /usr/share/nginx/html/index.html
COPY --from=assets /assets/app.js /usr/share/nginx/html/app.js
COPY --from=assets /assets/security-details.js /usr/share/nginx/html/security-details.js
COPY --from=assets /assets/security-keyboard.js /usr/share/nginx/html/security-keyboard.js
COPY --from=assets /assets/copy-link.js /usr/share/nginx/html/copy-link.js
COPY --from=assets /assets/theme.js /usr/share/nginx/html/theme.js
COPY --from=assets /assets/styles.css /usr/share/nginx/html/styles.css
COPY --from=assets /assets/shell.css /usr/share/nginx/html/shell.css
COPY --from=assets /assets/forecast.css /usr/share/nginx/html/forecast.css
COPY --from=assets /assets/theme.css /usr/share/nginx/html/theme.css
COPY --from=assets /assets/volumes /usr/share/nginx/html/volumes
COPY --from=assets /assets/dashboard /usr/share/nginx/html/dashboard
COPY --from=assets /assets/watchlist /usr/share/nginx/html/watchlist
COPY --from=assets /assets/analytics /usr/share/nginx/html/analytics
COPY --from=assets /tmp/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
