mkdir -p /usr/src/venv
virtualenv --python $(which python3) /usr/src/venv/hasanpikerbot

cat > /etc/systemd/system/hasanpikerbot.service <<EOM
[Unit]
Description=Hasan's Happy Bot
After=network.target

[Service]
Type=simple
User=tad
WorkingDirectory=/usr/src/hasanpikerbot
ExecStart=/usr/src/venv/hasanpikerbot/bin/python /usr/src/hasanpikerbot/main.py
StandardOutput=syslog
StandardError=syslog
Restart=always

[Install]
WantedBy=multi-user.target
EOM

systemctl enable /etc/systemd/system/hasanpikerbot.service
