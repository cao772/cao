FROM nginx:1.27-alpine

COPY apps/web/index.html /usr/share/nginx/html/index.html
COPY apps/web/styles.css /usr/share/nginx/html/styles.css
COPY apps/web/app.js /usr/share/nginx/html/app.js
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
