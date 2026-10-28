# CloudStack Card Clash

A booth game for the CloudStack Collaboration Conference. Each round presents a scenario, and the player has a budget and 150 seconds to design an Apache CloudStack architecture from cards, then an incident hits and the design either survives or doesn't. Scores go to a live leaderboard, and the admin page handles prize draws and attendee export.

Inspired by AWS Card Clash and the tournament layer in bilardi/aws-card-clash, but self-contained: no cloud account, no internet, no dependencies.

## Run it on the booth laptop

You need Python 3.9 or newer (macOS and most Linux distros already have it).

```
python3 server.py
```

The terminal prints three addresses and the admin PIN:

- `http://<laptop-ip>:8080/` is the game. Add `?kiosk=1` on the booth laptop so the screen returns to registration 60 seconds after each result.
- `http://<laptop-ip>:8080/leaderboard` goes on the big screen or a second monitor. It refreshes every 5 seconds.
- `http://<laptop-ip>:8080/admin` is for staff. Use the PIN from the terminal.

Set your own PIN and the address shown on the leaderboard:

```
ADMIN_PIN=482193 PUBLIC_URL=http://192.168.1.20:8080 python3 server.py
```

Or with Docker:

```
ADMIN_PIN=482193 docker compose up --build
```

Data lives in `data/clash.db` (SQLite). Back it up by copying the file.

### Letting attendees play on their phones

Run a hotspot or a travel router from the laptop, connect phones to it, and they open the address shown on the leaderboard. Don't rely on venue Wi-Fi: client isolation often blocks devices from reaching each other. Allow port 8080 through the laptop firewall.

The page loads Google Fonts if it can and falls back to system fonts if it can't, so it works fully offline.

## Logos

Put the official files in `web/logos/` (see `web/logos/README.txt` for the expected names). The Apache CloudStack and ShapeBlue logos show in the header of the game and the leaderboard, and partner logos show in a strip at the bottom and next to partner cards. The list of logos and file paths is under `branding` in `web/data/game.json`, so you can add or remove partners there. A missing file is skipped, and a partner without a file is shown by name. Logos are hidden during play so the board stays clear.

## ShapeBlue services

The registration page has one "New to CloudStack?" panel with QR codes for the guide, the docs and ShapeBlue, followed by all six ShapeBlue services (Consulting, IaaS Design and Build, VMware Migration, Training, Support, Software Engineering) with a "Talk to ShapeBlue" QR code.

After each round, the result screen picks the two services that fit what just happened:

- First, by scenario: VMware Migration for the VMware exit, Software Engineering for the Kubernetes and platform engineering scenarios, and IaaS Design and Build for the rest.
- Second, by result: Support if the incident took the cloud down, Training if fewer than half the requirements were met, otherwise Consulting.

QR codes link to the first service and the get-in-touch page. Edit the services, wording and scenario mapping under `shapeblue` in `web/data/game.json`.

## Learning links and QR codes

The registration page has a "New to CloudStack?" panel with QR codes for the illustrated guide (*Bitsy and the Great Cloud Tree*) and the official Apache CloudStack 4.23 docs.

After each round, the result screen shows a "Learn more" list. It starts with the feature that would have stopped the incident, followed by the missing requirements. Each item links to the matching chapter of the guide for beginners and to the docs page for architects. QR codes for the top item let players read it later on their own phone.

The QR codes are generated on the laptop (`web/vendor/qrcode.js`, the MIT-licensed qrcode-generator by Kazuhiko Arase), so they work without internet. The pages they point to need internet on the player's phone, which is why scanning is the main way in at the booth.

The mapping lives under `learn` in `web/data/game.json`: base URLs for the guide and docs, chapter titles, and for each requirement tag the guide chapter (`ch1` to `ch23`) and the docs path. Tags the story doesn't cover only have a docs link. To point at a different docs release, change `docs_url`.

## How a game works

There's one game mode. After registering, the player sees "Your scenario is ready" and presses **Start the clock**. Only then is the scenario revealed, both on screen and by the server, so nobody can read it ahead of time. After deploying they see their score and the incident, then choose **Play another scenario**, which starts the next round straight away with the clock running, or **New game** (which returns to registration for the next person). Players get scenarios they haven't played before until they've seen all 10. The leaderboard keeps each player's best score.

### Timing

- Each scenario has a 150-second clock (`time_limit` in `game.json`). The server allows 10 extra seconds for slow connections, then scores whatever was submitted.
- Reading the scenario is part of the 150 seconds, because it only appears once the clock starts.
- A round takes about 3 to 4 minutes including reading and the result screen, so one booth laptop handles roughly 15 players an hour.
- Each player can start **5 rounds per day** (`daily_round_limit`), so at most about 20 minutes of play per person per day. The count resets at midnight on the laptop's clock, so set it to UK time. Booth staff can give a player 5 extra rounds from the admin page.
- In kiosk mode (`?kiosk=1`) the result screen returns to registration after 60 seconds of no activity.

## Scenarios

SaaS launch, VMware exit, Retail edge rollout, Hosting provider public cloud, Kubernetes platform, AI research lab, Platform engineering team, Sovereign cloud for a bank, Telco network cloud, Hospital group.

Every scenario has a design that meets all requirements within budget.

## How scoring works

All scoring happens on the server from the cards submitted, so scores can't be edited in the browser.

- 100 points per requirement met
- If every requirement is met: 150 bonus, 10 per unused budget credit, 2 per second left
- Minus 25 for each card whose dependencies aren't in the design (for example a site-to-site VPN without a VPC)
- Plus 100 if the design survives the random incident, such as a host failure, ransomware, a phished admin password or the IPv4 pool running out
- Going over budget is blocked in the UI; a submitted over-budget build scores 0

Scenarios with more requirements are worth more points.

## Changing the game

Everything is in `web/data/game.json`, read by both the server and the browser:

- `cards`: name, category, cost, what the card `requires` and `provides` (tags)
- `scenarios`: brief, budget, required tags and which incidents can occur
- `incidents`: the tag that counters each one and the explanation shown
- `scoring`: the point values

Restart the server after editing. Each scenario has a known solution under budget; keep it that way when adjusting costs.

Before the event, check the card text against the release you're showcasing, especially GPU hosts, shared file systems, routed mode with BGP, ARM64 hosts and Cluster DRS.

Partner cards (StorPool, LINSTOR/LINBIT, Sendense) are marked with a `partner` field and a gold outline. Confirm the wording with each sponsor before the event, and add more for other sponsors in the same way.

## Prizes and attendee data

On the admin page you can:

- see every player, their best score, rounds left today and whether they opted in to news
- give a player 5 extra rounds for today
- award a prize to anyone, such as the top three at the closing session
- draw a random winner from players who finished at least one game and haven't won yet (optionally only today's players)
- export all players, or only those who opted in to news, as CSV
- delete all data after the event

The registration form asks for name, email, optional company and role. Players must accept the rules (leaderboard name on screen, contact if they win). The news opt-in is separate and unticked by default. Only use the "news opt-ins only" export for marketing, and delete the data once prizes are delivered and the opt-in list has been handed over. Check the wording with whoever handles GDPR for the event.

## Where to host it

The recommended setup is the booth laptop with its own Wi-Fi: a travel router or hotspot, ideally with a 4G or 5G uplink so phones can open the learning links. It keeps working if the venue Wi-Fi fails, the attendee data never leaves the laptop, and there's nothing to secure on the internet.

If you also want people to play from their seats or after the event, run a second copy on a small Linux VM (1 vCPU and 1 GB RAM is plenty), ideally on CloudStack itself, behind a reverse proxy such as Caddy for HTTPS. Before exposing it:

- set a long `ADMIN_PIN` and restrict `/admin` and `/api/admin/` to your IP or a VPN at the proxy, because the PIN alone is a booth-level lock
- set `PUBLIC_URL` to the public address so the leaderboard shows it
- remember attendee data is now on that server; delete it after the event

A static host such as Netlify or GitHub Pages won't work on its own, because the scoring, leaderboard and attendee data need the Python server.

## Notes

- One registration per email. Registering again with the same email updates the details and continues as the same player, including the rounds they've used today.
- Databases from earlier versions upgrade automatically when the server starts.
- The admin PIN is a light lock for a booth, not real security. Don't expose the server to the internet.
- "Apache", "CloudStack" and "Apache CloudStack" are trademarks of the Apache Software Foundation. Run the game name and partner cards past the PMC before the event.
