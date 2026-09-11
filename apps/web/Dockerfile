FROM nginx:1.27-alpine

COPY apps/web/index.html /usr/share/nginx/html/index.html
COPY apps/web/styles.css /usr/share/nginx/html/styles.css
COPY apps/web/settings.css /usr/share/nginx/html/settings.css
COPY apps/web/app.js /usr/share/nginx/html/app.js
COPY apps/web/settings.js /usr/share/nginx/html/settings.js
COPY apps/web/settings-projects.js /usr/share/nginx/html/settings-projects.js
COPY apps/web/settings-local-scope.js /usr/share/nginx/html/settings-local-scope.js
COPY apps/web/settings-policy.js /usr/share/nginx/html/settings-policy.js
COPY apps/web/settings-model.js /usr/share/nginx/html/settings-model.js
COPY apps/web/settings-nodes.js /usr/share/nginx/html/settings-nodes.js
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
