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
| `SELF_SERVICE_CHANNEL_ID` | Yes | — | Channel where Worf posts the self-service panel |
| `ADMIN_REQUEST_CHANNEL_ID` | Yes | — | Channel for admin role-request review; slash commands only work here |
| `ADMIRAL_MANAGEMENT_CHANNEL_ID` | Yes | — | Channel where Worf posts the admiral management panel (Remove Role / Remove Player) |
| `ADMIN_ROLE_ID` | Yes | — | Role ID of the admin role — tagged on requests and grants management panel access |
| `LEADERSHIP_CATEGORY_ID` | Yes | — | Category under which temporary per-alliance approval channels are created |
| `GUILD_ID` | No | `0` | Guild ID for instant slash-command registration. Omit to sync globally (≤1 hr) |
| `SERVER_ROLE_ID` | No | `0` | Role assigned automatically when a user completes the Alliance form |
| `ADMIRAL_ROLE_ID` | No | `0` | Role ID of the Admiral role |
| `COMMODORE_ROLE_ID` | No | `0` | Role ID of the Commodore role |
| `FIRST_OFFICER_ROLE_ID` | No | `0` | Role ID of the First Officer role |
| `ROE_OFFICER_ROLE_ID` | No | `0` | Role ID of the RoE Officer role |
| `DIPLOMACY_OFFICER_ROLE_ID` | No | `0` | Role ID of the Diplomacy Officer role |

> To find an ID: enable Developer Mode (*User Settings → Advanced → Developer Mode*). Right-click a channel/category/role and choose **Copy ID**. A role value of `0` disables that request button.

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

## Slash Commands

All slash commands are restricted to the `ADMIN_REQUEST_CHANNEL_ID` channel.

All slash commands are restricted to the `ADMIN_REQUEST_CHANNEL_ID` channel.

| Command | Description |
|---|---|
| `/addalliance <tag>` | Register an alliance tag that existed before Worf started. The role named `TAG` must already exist on the server. |
| `/addadmiral <tag> <user>` | Register a pre-existing admiral for an alliance. The user must already hold the Admiral role. |
| `/listadmirals` | Display the current admiral roster (tag → member). |
| `/setrolelist <channel>` | Set the channel where Worf maintains the live alliance role roster. If a channel was already set, the old post is deleted and a new one is created in the new channel. |

**First-time setup order:**
1. `/addalliance TREK` — register the alliance
2. `/addadmiral TREK @Username` — assign the admiral
3. `/setrolelist #some-channel` — start the live role roster

After steps 1–2, any Commodore/First Officer/RoE Officer/Diplomacy Officer request from a `[TREK]` member will create a private channel for that alliance's admiral to approve, rather than posting to the admin channel.

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

### Role Requests — Admiral

1. User clicks **Request Admiral Access** → ephemeral confirmation sent to user.
2. An embed is posted in the admin channel, tagging `ADMIN_ROLE_ID`.
3. Admin clicks **Approve** → role assigned, confirmation posted, buttons disabled.
4. Admin clicks **Deny** → denial posted, buttons disabled.
5. On approval, Worf records `{alliance_tag: user_id}` in the admiral roster (extracted from the user's `[TAG] Name` nickname).

### Role Requests — Commodore / First Officer / RoE Officer / Diplomacy Officer

1. User clicks a role button → Worf reads their alliance tag from their nickname (`[TAG]` prefix) or their alliance role.
2. **If an admiral is registered for that alliance:**
   - Worf creates a private text channel under `LEADERSHIP_CATEGORY_ID`.
   - Channel is visible only to that specific admiral member and the admin role (not the whole Admiral role).
   - Both are tagged in the message. The user receives an ephemeral message: *"sent to your alliance admiral for review."*
   - After Approve/Deny, a confirmation is posted and the channel is deleted after 10 seconds.
3. **If no admiral is registered** (or no alliance tag found, or category not configured):
   - Falls back to the admin channel, tagging `ADMIN_ROLE_ID` with a note explaining why.

Approval buttons survive bot restarts — they encode the user ID and role ID in the `custom_id` rather than relying on in-memory view state.

### Admiral Management Panel

A persistent panel is posted in `ADMIRAL_MANAGEMENT_CHANNEL_ID`. Both admirals and admins can use it.

**Remove Role**
1. Click the button → modal asking for member name and role name.
2. Accepted role names: `Commodore`, `First Officer`, `RoE Officer`, `Diplomacy Officer` (case-insensitive).
3. Worf verifies the requester is the registered admiral of the same alliance as the target (or has the admin role).
4. If valid, the role is stripped and the role roster updates automatically.

**Remove Player from Alliance**
1. Click the button → modal asking for the member's name (without `[TAG]` prefix).
2. Worf verifies same-alliance or admin.
3. Strips: alliance tag role, Admiral, Commodore, First Officer, RoE Officer, Diplomacy Officer roles.
4. Removes the `[TAG]` prefix from the player's nickname.
5. If the player was a registered admiral, they are removed from the admiral roster.
6. Role roster updates automatically.

### Alliance Role Roster

Set with `/setrolelist <channel>`. Worf maintains a single embed in that channel:

```
[TREK]
Admiral: Thunder
Commodore: Player1
1st Officer: Player2
RoE Officer: Player3, Player4
Diplomacy Officer: Thunder   ← admiral fills in when nobody holds the role

[BORG]
Admiral: SomePlayer
...
```

- Usernames are stripped of their `[TAG]` prefix.
- If no member in the alliance holds a role, the admiral's name appears as the placeholder.
- The embed updates automatically after every approval, removal, or `/addadmiral`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| *"I do not have permission to update your nickname"* | Move Worf's role above members' roles in *Server Settings → Roles*. |
| *"I do not have permission to assign/remove …"* | Move Worf's role above the target role in the server hierarchy. |
| Slash commands not appearing | Set `GUILD_ID` for instant registration, or wait up to 1 hour for global sync. |
| Leadership channel not created | Verify `LEADERSHIP_CATEGORY_ID` is a category (not a channel) and Worf has *Manage Channels* permission in it. |
| Sub-role requests going to admin channel unexpectedly | Run `/listadmirals`; check the user's nickname starts with `[TAG]`. |
| *"You are not the registered admiral"* | The requester's user ID doesn't match the admiral stored for their tag. Run `/addadmiral TAG @User` to fix. |
| *"Could not find a member named …"* | The name must match the player's nickname **without** the alliance tag prefix, case-insensitive. |
| Role roster not updating | Check `ROLE_LIST_CHANNEL_ID` is set via `/setrolelist` and Worf has *Send Messages* in that channel. |
| Worf posts a new panel on every restart | Ensure `./data` is a persistent bind mount (check `docker-compose.yml` volumes). |
| Buttons stop working after restart | Buttons use persistent `custom_id` routing — check logs with `docker compose logs -f worf`. |
