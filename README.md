# Worf — STFC Discord Server Management Bot

Worf is a Discord bot that manages role assignment and server nicknames through a single self-service panel. Users interact with it via buttons; admins approve or deny role requests in a dedicated channel.

---

## Features

- **Alliance & In-Game Name**: modal prompt renames the user's server nickname to `[TAG] Name` and auto-creates/assigns the 4-letter alliance role.
- **Role requests** (Admiral, Commodore, First Officer, RoE Officer, Diplomacy Officer): sends an approve/deny card to an admin channel; notifies the requester ephemerally; posts a confirmation once actioned.
- **Persistent panel**: on restart Worf edits its existing self-service post rather than creating a duplicate.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Docker | 24+ |
| Docker Compose | v2 (plugin, not standalone) |

---

## Discord Bot Setup

1. Go to <https://discord.com/developers/applications> and create a new application named **Worf**.
2. Under **Bot**:
   - Click **Add Bot**.
   - Copy the **Token** — this is your `DISCORD_TOKEN`.
   - Enable **SERVER MEMBERS INTENT** and **MESSAGE CONTENT INTENT** under *Privileged Gateway Intents*.
3. Under **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Manage Nicknames`, `Manage Roles`, `Send Messages`, `Read Message History`, `View Channels`
   - Open the generated URL and invite Worf to your server.
4. In your Discord server:
   - Drag **Worf**'s role **above** the Admiral/Commodore/First Officer/RoE Officer/Diplomacy Officer roles in *Server Settings → Roles*. Discord requires a bot's role to sit above any role it manages.
   - Worf's role must be below *Server Owner* — it can never rename the owner.

### Finding Channel IDs

Enable Developer Mode in Discord (*User Settings → Advanced → Developer Mode*), then right-click a channel and choose **Copy Channel ID**.

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```
cp .env.example .env
```

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | Yes | — | Bot token from the Developer Portal |
| `SELF_SERVICE_CHANNEL_ID` | Yes | — | Channel ID where Worf posts the self-service panel |
| `ADMIN_REQUEST_CHANNEL_ID` | Yes | — | Channel ID where role requests appear for admin review |
| `ADMIRAL_ROLE_NAME` | No | `Admiral` | Exact name of the Admiral role on your server |
| `COMMODORE_ROLE_NAME` | No | `Commodore` | Exact name of the Commodore role |
| `FIRST_OFFICER_ROLE_NAME` | No | `First Officer` | Exact name of the First Officer role |
| `ROE_OFFICER_ROLE_NAME` | No | `RoE Officer` | Exact name of the RoE Officer role |
| `DIPLOMACY_OFFICER_ROLE_NAME` | No | `Diplomacy Officer` | Exact name of the Diplomacy Officer role |

> Role name variables must match **exactly** (including capitalisation and spaces) the role names on your Discord server.

---

## Directory Structure

```
stfc-discord-bot/
├── bot/
│   ├── main.py          # Bot source code
│   ├── requirements.txt
│   └── Dockerfile
├── data/                # Created automatically; stores the self-service message ID
│   └── bot_state.json
├── docker-compose.yml
├── .env                 # Your secrets — never commit this
├── .env.example
└── README.md
```

The `data/` directory is created automatically by Docker Compose on first run and persisted as a bind mount. It stores `bot_state.json` so Worf can find and edit its self-service panel after restarts rather than posting a new one each time.

---

## Running Worf

```bash
# First run (builds the image)
docker compose up -d --build

# View logs
docker compose logs -f worf

# Stop
docker compose down

# Restart after a code change
docker compose up -d --build
```

---

## How It Works

### Self-Service Panel

On startup Worf looks for a stored message ID in `data/bot_state.json`. If found it edits that message; otherwise it posts a new one and saves the ID. The panel has six buttons arranged across rows:

```
[ Change Alliance & In-Game Name  ]
[ Request Admiral Access ] [ Request Commodore Access ]
[ Request First-Officer Access ] [ Request RoE Officer Access ]
[ Request Diplomacy Officer Access ]
```

### Change Alliance & In-Game Name

1. User clicks the button → a modal appears asking for **In-Game Name** and **Alliance Tag**.
2. Alliance Tag is validated: must be exactly 4 characters, letters A–Z only. Stored as uppercase.
3. Worf renames the user to `[TAG] In-Game Name`.
4. Worf checks whether a role named `TAG` exists. If not, it creates one. Either way, the role is assigned to the user.

### Role Requests

1. User clicks a role button → they receive an ephemeral message: *"Your request … is under review."*
2. An embed is posted in the admin channel with **Approve** / **Deny** buttons.
3. An admin clicks **Approve**:
   - Worf assigns the role to the user.
   - A confirmation message is posted in the admin channel.
   - The approve/deny buttons are disabled on the original request card.
4. An admin clicks **Deny**:
   - A denial message is posted in the admin channel.
   - The buttons are disabled.

Approval buttons survive bot restarts — Worf handles them via the interaction's `custom_id` rather than in-memory view state.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| *"I do not have permission to update your nickname"* | Move Worf's role above members' roles. Worf cannot rename users whose top role is equal to or above its own. |
| *"I do not have permission to assign …"* | Move Worf's role above the target role in the server hierarchy. |
| Worf posts a new panel on every restart | Ensure `./data` is a persistent bind mount (check `docker-compose.yml` volumes). |
| Buttons stop working after restart | This should not happen — buttons use persistent `custom_id` routing. If it does, check logs with `docker compose logs -f worf`. |
