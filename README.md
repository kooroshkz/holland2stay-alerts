<div align="center">

# holland2stay-alerts

**Know the moment a Holland2Stay (soon Codomo) home matching your search is listed.**

Self-hosted. One command. Alerts on Telegram, Discord, ntfy, Slack, email and 100+ other apps.

[![CI](https://github.com/kooroshkz/holland2stay-alerts/actions/workflows/ci.yml/badge.svg)](https://github.com/kooroshkz/holland2stay-alerts/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-black)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-black)
![Docker](https://img.shields.io/badge/docker-amd64%20%7C%20arm64-black)

[Website](https://kooroshkz.github.io/holland2stay-alerts) · [Live demo](https://kooroshkz.github.io/holland2stay-alerts/demo/) · [Quick start](#quick-start)

<img src="docs/assets/dashboard.png" alt="Dashboard" width="820">

</div>

## Why

Good homes on Holland2Stay are gone within minutes, and refreshing the site all day is no way
to live. This checks the listings for you and messages you when something matches your cities,
size and budget, so you can book it before everyone else.

## Quick start

### Docker

```bash
docker run -d --name h2s-alerts --restart unless-stopped \
  -e H2S_CITIES="Eindhoven, Rotterdam" \
  -e H2S_BEDROOMS="studio, loft, 1" \
  -e H2S_PRICE_MAX=1600 \
  -e H2S_NOTIFY="tgram://BOT_TOKEN/CHAT_ID" \
  -v h2s-data:/data -p 127.0.0.1:8080:8080 \
  ghcr.io/kooroshkz/holland2stay-alerts
```

The dashboard is on [localhost:8080](http://localhost:8080). To open it to other devices, publish
the port without `127.0.0.1:` and set `H2S_DASHBOARD_PASSWORD`. Works on a Raspberry Pi or a NAS too.
Prefer Compose? See [docker-compose.yml](docker-compose.yml).

### Python

```bash
pipx install git+https://github.com/kooroshkz/holland2stay-alerts
h2s-alerts init     # a few questions, then a test message
h2s-alerts watch
```

Needs Python 3.11 or newer. Keep it running on any computer that stays on.

## What you get

- **New homes** matching your search, once each, with city, size, price and contract
- **Back on the market**: homes that come back after someone didn't pay
- **Lottery**: new lottery homes on Tuesday evening, with the Sunday 20:00 deadline, and a
  message when a lottery home becomes directly bookable
- **Price drops** on homes you're already watching
- **New buildings**, weeks before they go on sale
- **A dashboard** with what's available, what got taken and how fast, and the hours new homes
  usually show up
- **Many at once** come as one message, not twenty
- **Quiet hours**: alerts wait, and you only get the ones that are still available
- **Health notices** if Holland2Stay blocks requests or changes something

## Notifications

Alerts go through [Apprise](https://github.com/caronc/apprise/wiki), so almost any app works.
Add one link per app:

| App | Link |
|---|---|
| Telegram | `tgram://BOT_TOKEN/CHAT_ID` ([make a bot](https://core.telegram.org/bots#how-do-i-create-a-bot)) |
| Discord | `discord://WEBHOOK_ID/WEBHOOK_TOKEN` |
| ntfy | `ntfy://a-long-secret-topic` (free push to your phone, no account) |
| Slack | `slack://TOKEN_A/TOKEN_B/TOKEN_C/#channel` |
| Email | `mailtos://you:app-password@gmail.com` |
| Signal, Matrix, Pushover, Gotify, Home Assistant, webhooks… | [all options](https://github.com/caronc/apprise/wiki) |

Check them with `h2s-alerts test`. A new home looks like this:

```
Havenkade 136-B
Eindhoven · Loft · €1,695
Indefinite · Furnished
https://www.holland2stay.com/residences/havenkade-136-b.html
```

## Configuration

Run `h2s-alerts init`, or copy [config.example.toml](config.example.toml) to `config.toml`:

```toml
[search]
cities = ["Eindhoven", "Rotterdam"]   # empty = everywhere
bedrooms = ["studio", "loft", "1"]    # or "2+", "1-3"
price_max = 1600
contract = ["long"]                   # long or short stay

[notify]
urls = ["tgram://BOT_TOKEN/CHAT_ID"]
```

Every setting also works as an environment variable, which is handy for Docker:

| Variable | Example | |
|---|---|---|
| `H2S_CITIES` | `Eindhoven, The Hague` | `h2s-alerts cities` lists names |
| `H2S_EXCLUDE_CITIES` | `Maastricht` | everywhere except these |
| `H2S_BEDROOMS` | `studio, 2+` | studio, loft, 1, 2, 3, 4 |
| `H2S_PRICE_MIN` / `H2S_PRICE_MAX` | `1600` | euro per month, all in |
| `H2S_CONTRACT` | `long` | long, short, indefinite, 2y, 1y, 6m, 4m |
| `H2S_FURNISHING` | `furnished` | fully-furnished, furnished, semi-furnished, unfurnished |
| `H2S_OCCUPANTS` | `couple` | one, couple, two, family, three, four |
| `H2S_MOVE_IN_BEFORE` | `2027-02-01` | |
| `H2S_LOTTERY` | `true` | lottery homes too |
| `H2S_NOTIFY` | `tgram://… ntfy://…` | separate links with a space |
| `H2S_NOTIFY_FILE` | `/run/secrets/h2s` | read the links from a file |
| `H2S_QUIET_HOURS` | `23:00-07:00` | |
| `H2S_SCHEDULE` | `normal` | relaxed, normal or eager |
| `H2S_DASHBOARD` / `H2S_PORT` / `H2S_HOST` | `on` / `8080` / `0.0.0.0` | |
| `H2S_DASHBOARD_PASSWORD` | | when it's reachable from other devices |
| `H2S_DATA_DIR` | `/data` | |
| `H2S_CONFIG` | `/config/config.toml` | |

## Commands

| | |
|---|---|
| `h2s-alerts init` | set up your search and notifications |
| `h2s-alerts watch` | keep checking and send alerts (the default) |
| `h2s-alerts list` | what matches right now (`--lottery`, `--city`, `--json`) |
| `h2s-alerts test` | send a test message to every app |
| `h2s-alerts doctor` | check your setup |
| `h2s-alerts stats` | what the watcher has seen so far |
| `h2s-alerts cities` | city names you can use |
| `h2s-alerts demo` | try the dashboard with sample data |
| `h2s-alerts mcp` | MCP server for AI assistants |

## How often it checks

Most homes are released on weekdays during office hours, plus a small batch just after
midnight when unpaid reservations go back on sale. So it checks more often then and less
at night:

| | relaxed | normal | eager |
|---|---|---|---|
| Weekdays 08:30 to 18:00, and 00:05 to 00:45 | 5 min | 2 min | 1 min |
| Rest of the day | 10 min | 5 min | 3 min |
| Night | 30 min | 15 min | 10 min |

Each check is a single small request with your filters, so the load on their site is tiny.
It never goes below one minute, adds a bit of randomness, says who it is in the user agent,
and backs off when Holland2Stay asks it to.

## Ask an AI assistant

`h2s-alerts mcp` runs an [MCP](https://modelcontextprotocol.io) server, so Claude, Cursor and
others can answer "any studios in Eindhoven under €1,300?". Install the extra first:

```bash
pipx install "holland2stay-alerts[mcp] @ git+https://github.com/kooroshkz/holland2stay-alerts"
```

```json
{ "mcpServers": { "holland2stay": { "command": "h2s-alerts", "args": ["mcp"] } } }
```

## Home Assistant

Send alerts to Home Assistant with an Apprise link (`hassio://…`), or read the dashboard's
JSON from `http://HOST:8080/api/overview` with a REST sensor.

## Tips for actually getting a home

- Create your Holland2Stay account and pay the registration fee before you start looking.
- Have your documents ready. After booking you have about a day to pay.
- Keep a browser tab open and stay logged in, so an alert is one tap away from booking.
- In the lottery, homes with fewer sign-ups give you better odds.

## FAQ

**Does it book for me?** No, and it never will. Booking with automated tools is against
Holland2Stay's terms. It tells you, you book.

**Is this allowed?** It reads public listing information at a slow pace and identifies itself.
Read [Holland2Stay's terms](https://www.holland2stay.com/terms-and-conditions) and decide for
yourself. You're responsible for how you use it.

**Holland2Stay is becoming Codomo.** When listings move, set `base_url` (or `H2S_BASE_URL`) to the
new site, or update to the latest release.

**Alerts stopped.** Run `h2s-alerts doctor`. If Holland2Stay changed something, open an
[issue](https://github.com/kooroshkz/holland2stay-alerts/issues).

## Contributing

Ideas, fixes and other landlords are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Disclaimer

This is an unofficial, independent project. It is not affiliated with, endorsed by or
connected to Holland2Stay B.V. or Codomo. Their names are only used to describe what this
works with. It never books, pays, fills in forms or logs in. There's no guarantee you'll get
a home, and it can stop working whenever the site changes. Provided as is, under the
[MIT license](LICENSE).
