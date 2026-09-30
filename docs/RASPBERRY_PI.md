# Raspberry Pi setup

Connect the Raspberry Pi and the phones to your existing Wi-Fi network. The application does not configure networking; no dedicated hotspot or Ethernet uplink is required. Commands below are for the actual Pi. The same manual app startup works on Ubuntu.

## 1. Install and run the app

Connect the Pi to your normal Wi-Fi network using its desktop network menu. Copy this repository into **/home/YOUR_USERNAME/tournamentManager**, then open a terminal there.

```bash
sudo apt update
sudo apt install python3-venv python3-pip
cd ~/tournamentManager
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

On the Pi, open http://localhost:8080. On another device on the existing home network, use http://PI_WIFI_IP:8080. Find the address with:

```bash
hostname -I
```

Installation needs internet to download packages; normal operation does not. Stop the foreground app with Ctrl+C before starting the service.

## 2. Start automatically on boot

The provided template assumes this repository is at /home/YOUR_USERNAME/tournamentManager. If you chose another path, edit WorkingDirectory and ExecStart in deploy/tournament@.service first.

Create the persistent data directory **as your normal Pi user**:

```bash
mkdir -p ~/.local/share/local-league
sudo cp deploy/tournament@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now "tournament@$(id -un).service"
```

The service runs as your normal user and stores its database in ~/.local/share/local-league/. If you already created a tournament with the foreground app, export a JSON backup before stopping it, then restore that file through the service's web interface.

```bash
systemctl status "tournament@$(id -un).service"
journalctl -u "tournament@$(id -un).service" -n 50 --no-pager
sudo systemctl restart "tournament@$(id -un).service"
```

The app starts without waiting for internet. It listens on port 8080 on the host’s network interfaces, including its existing Wi-Fi connection.

## 3. Open the app on phones

Keep the host connected to the same local network as the phones. Start the app with `.venv/bin/python run.py`, or use the optional service above.

Find the host’s Wi-Fi IPv4 address in its network settings or with `hostname -I`. If several addresses appear, choose the one belonging to your Wi-Fi connection, not a VPN or container network. For example, if that address is `192.168.178.57`, phones open:

**http://192.168.178.57:8080**

That address is an example; use the address assigned to your own host. `localhost` on a phone refers to the phone, not the host.

Open **Tournament setup** to display a QR code that other phones can scan. The code and displayed link automatically use the host’s local network IP, even if you opened the app through localhost. The QR opens the app; phones should already be connected to the network. An optional DHCP address reservation in your router can keep the host’s address stable.

The app defaults to `TOURNAMENT_HOST=0.0.0.0`, which accepts connections from other devices. If you previously set this variable to `127.0.0.1`, stop that app instance and restart it with:

```bash
TOURNAMENT_HOST=0.0.0.0 .venv/bin/python run.py
```

If phones cannot connect, check that the host’s firewall allows TCP 8080 from your local network and that the Wi-Fi network does not isolate clients. Guest networks sometimes prevent devices from communicating. No router port forwarding is needed. Keep the host awake while playing.

## 4. Rehearse before the event

- Connect the host and two phones to the existing Wi-Fi.
- Open the app on each phone using the host’s Wi-Fi address.
- Submit a practice result and check that the other phone sees it within about five seconds.
- Restart the app and confirm the result is still present.
- If you enabled the optional startup service, reboot the host and verify it starts.
- Export and restore a practice backup, then reset for the real tournament.
- Confirm the host’s date/time. Internet is not required during the tournament, but the local Wi-Fi connection must stay available.

The app has automated desktop/mobile browser tests. Actual Wi-Fi coverage, phone connectivity, firewall rules, and optional boot startup need an on-device rehearsal.

## Recovery

If the app is unavailable, check the service logs and whether the host and phone are on the same local network. If the hostname does not resolve, use the direct IP. The database remains on disk through app restarts.

Use the in-app JSON export for routine backups. Before copying the raw database directory, stop the service so all SQLite files are copied consistently:

```bash
sudo systemctl stop "tournament@$(id -un).service"
cp -a ~/.local/share/local-league ~/local-league-backup
sudo systemctl start "tournament@$(id -un).service"
```

Use a new destination if that backup folder already exists. Automatic backups before reset/restore are in ~/.local/share/local-league/backups/.

Official reference: [Raspberry Pi networking](https://www.raspberrypi.com/documentation/computers/configuration.html).
