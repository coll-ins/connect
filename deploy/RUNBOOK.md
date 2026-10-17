# CONNECT deploy runbook (Ubuntu 24.04, single VPS). DOMAIN = your domain.
0. sed -i 's/connect.example.com/DOMAIN/g' deploy/nginx-connect.conf deploy/connect.env.example
1. DNS: A record DOMAIN -> VPS IP; wait until `dig +short DOMAIN` shows it.
2. sudo apt update && sudo apt install -y nginx postgresql redis-server certbot python3-venv git rsync
   sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw --force enable
   sudo systemctl enable --now postgresql redis-server
   ss -ltn | grep 6379      # must show 127.0.0.1 only
3. sudo useradd -r -m -d /srv/connect -s /bin/bash connect
   sudo mkdir -p /etc/connect /var/log/connect /var/backups/connect
   sudo chown connect:connect /var/log/connect /var/backups/connect
4. sudo -u postgres psql -c "CREATE ROLE connect LOGIN PASSWORD 'CHANGE_ME' CREATEDB;"
   sudo -u postgres createdb -O connect connect
5. sudo -u connect git clone <repo-url> /srv/connect      # (deploy key or token if private)
   sudo -u connect python3 -m venv /srv/connect/venv
   sudo -u connect /srv/connect/venv/bin/pip install -r /srv/connect/backend/requirements.txt
6. sudo cp /srv/connect/deploy/connect.env.example /etc/connect/connect.env   # edit every value
   sudo chown root:connect /etc/connect/connect.env && sudo chmod 640 /etc/connect/connect.env
7. Frontend (on your laptop): cd frontend-react && npm ci && npm run build
   rsync -az --delete dist/ USER@VPS:/tmp/dist/
   (on VPS) sudo mkdir -p /srv/connect/frontend-react && sudo rsync -a --delete /tmp/dist/ /srv/connect/frontend-react/dist/ && sudo chown -R connect:connect /srv/connect/frontend-react
8. sudo -u connect bash -c 'set -a; . /etc/connect/connect.env; set +a; cd /srv/connect/backend; V=/srv/connect/venv/bin/python; $V manage.py check --deploy --fail-level WARNING; $V manage.py migrate; $V manage.py collectstatic --noinput; $V manage.py createcachetable || true; $V manage.py createsuperuser'
9. TLS: sudo systemctl stop nginx
   sudo certbot certonly --standalone -d DOMAIN --pre-hook "systemctl stop nginx" --post-hook "systemctl start nginx"
10. sudo cp /srv/connect/deploy/connect-daphne@.service /etc/systemd/system/ && sudo systemctl daemon-reload
    sudo systemctl enable --now connect-daphne@8001 connect-daphne@8002
11. sudo cp /srv/connect/deploy/nginx-connect.conf /etc/nginx/sites-available/connect
    sudo ln -sf /etc/nginx/sites-available/connect /etc/nginx/sites-enabled/connect && sudo rm -f /etc/nginx/sites-enabled/default
    sudo nginx -t && sudo systemctl start nginx
12. sudo cp /srv/connect/deploy/connect.cron /etc/cron.d/connect && sudo chmod 644 /etc/cron.d/connect
    sudo cp /srv/connect/deploy/logrotate-connect /etc/logrotate.d/connect
13. /srv/connect/deploy/smoke_test.sh https://DOMAIN        # every line must PASS
14. Paystack dashboard (Settings > API Keys & Webhooks): set the webhook URL to https://DOMAIN/api/bookings/webhooks/paystack/
    Paystack takes ONE URL per mode; refund.* events are routed to the refund handler internally.
15. Run backup.sh and restore_test.sh once on the VPS (as `connect`, env loaded); configure rclone and set OFFSITE_REMOTE.
16. Update procedure: git pull; pip install -r requirements.txt; migrate; collectstatic;
    systemctl restart connect-daphne@8001; sleep 8; systemctl restart connect-daphne@8002
