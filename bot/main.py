import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import json
import re
import logging
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('worf')

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
SELF_SERVICE_CHANNEL_ID = int(os.getenv('SELF_SERVICE_CHANNEL_ID', '0'))
ADMIN_REQUEST_CHANNEL_ID = int(os.getenv('ADMIN_REQUEST_CHANNEL_ID', '0'))
ADMIRAL_MANAGEMENT_CHANNEL_ID = int(os.getenv('ADMIRAL_MANAGEMENT_CHANNEL_ID', '0'))
SERVER_ROLE_ID = int(os.getenv('SERVER_ROLE_ID', '0'))
LEADERSHIP_CATEGORY_ID = int(os.getenv('LEADERSHIP_CATEGORY_ID', '0'))
ADMIN_ROLE_ID = int(os.getenv('ADMIN_ROLE_ID', '0'))
GUILD_ID = int(os.getenv('GUILD_ID', '0'))

ROLE_IDS: dict[str, int] = {
    'admiral': int(os.getenv('ADMIRAL_ROLE_ID', '0')),
    'commodore': int(os.getenv('COMMODORE_ROLE_ID', '0')),
    'first_officer': int(os.getenv('FIRST_OFFICER_ROLE_ID', '0')),
    'roe_officer': int(os.getenv('ROE_OFFICER_ROLE_ID', '0')),
    'diplomacy_officer': int(os.getenv('DIPLOMACY_OFFICER_ROLE_ID', '0')),
}

# Roles routed via admiral/leadership channel
LEADERSHIP_ROLES = frozenset({'commodore', 'first_officer', 'roe_officer', 'diplomacy_officer'})

# Roles that can be removed via the management panel (not admiral — only admin removes admirals)
REMOVABLE_ROLES = ('commodore', 'first_officer', 'roe_officer', 'diplomacy_officer')

# Display order in the role roster
ROLE_DISPLAY_ORDER = [
    ('commodore', 'Commodore'),
    ('first_officer', '1st Officer'),
    ('roe_officer', 'RoE Officer'),
    ('diplomacy_officer', 'Diplomacy Officer'),
]

ROLE_NAME_MAP: dict[str, str] = {
    'commodore': 'commodore',
    'first officer': 'first_officer',
    '1st officer': 'first_officer',
    'roe officer': 'roe_officer',
    'roe': 'roe_officer',
    'diplomacy officer': 'diplomacy_officer',
    'diplomacy': 'diplomacy_officer',
}

APPROVAL_PREFIXES = ('worf:approve:', 'worf:deny:', 'worf:ch_approve:', 'worf:ch_deny:')

STATE_FILE = '/data/bot_state.json'

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state() -> dict:
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs('/data', exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def get_alliance_tag(member: discord.Member) -> str | None:
    """Extract [TAG] from nickname, falling back to a bare 4-letter role name."""
    if member.nick:
        m = re.match(r'^\[([A-Z]{4})\]', member.nick)
        if m:
            return m.group(1)
    for role in member.roles:
        if re.match(r'^[A-Z]{4}$', role.name):
            return role.name
    return None


def strip_alliance_tag(display_name: str) -> str:
    """Remove [TAG] prefix and leading whitespace from a display name."""
    return re.sub(r'^\[[A-Z]{4}\]\s*', '', display_name).strip()


def find_member_by_name(guild: discord.Guild, name: str) -> discord.Member | None:
    """Case-insensitive search by stripped display name or Discord username."""
    name_lower = name.lower().strip()
    for member in guild.members:
        if strip_alliance_tag(member.display_name).lower() == name_lower:
            return member
        if member.name.lower() == name_lower:
            return member
    return None


def verify_requester(
    requester: discord.Member,
    target: discord.Member,
    guild: discord.Guild,
) -> tuple[bool, str]:
    """
    Returns (authorised, error_message).
    Admins may act on any member; admirals only within their own alliance.
    """
    if ADMIN_ROLE_ID:
        admin_role = guild.get_role(ADMIN_ROLE_ID)
        if admin_role and admin_role in requester.roles:
            return True, ''

    state = load_state()
    req_tag = get_alliance_tag(requester)
    if not req_tag:
        return False, 'You do not have an alliance tag. Complete the Alliance & In-Game Name form first.'

    if state.get('admirals', {}).get(req_tag) != requester.id:
        return False, 'You are not the registered admiral of your alliance.'

    target_tag = get_alliance_tag(target)
    if target_tag != req_tag:
        tag_str = f'`{target_tag}`' if target_tag else 'no alliance'
        return False, f'That player ({tag_str}) is not in your alliance (`{req_tag}`).'

    return True, ''

# ---------------------------------------------------------------------------
# Role roster embed
# ---------------------------------------------------------------------------

def generate_role_list_embed(guild: discord.Guild, state: dict) -> discord.Embed:
    alliances: list[str] = state.get('alliances', [])
    admirals_map: dict[str, int] = state.get('admirals', {})

    embed = discord.Embed(
        title='Alliance Role Roster',
        color=discord.Color.gold(),
    )

    if not alliances:
        embed.description = 'No alliances are currently registered.'
        return embed

    for tag in sorted(alliances):
        alliance_role = discord.utils.get(guild.roles, name=tag)
        admiral_id = admirals_map.get(tag)
        admiral_member = guild.get_member(admiral_id) if admiral_id else None
        admiral_name = strip_alliance_tag(admiral_member.display_name) if admiral_member else '*(vacant)*'

        lines = [f'**Admiral:** {admiral_name}']

        for role_key, label in ROLE_DISPLAY_ORDER:
            role_id = ROLE_IDS.get(role_key, 0)
            if not role_id:
                continue
            role = guild.get_role(role_id)
            if role is None:
                continue

            if alliance_role:
                holders = [m for m in role.members if alliance_role in m.roles]
            else:
                holders = list(role.members)

            if holders:
                names = ', '.join(strip_alliance_tag(m.display_name) for m in holders)
                lines.append(f'**{label}:** {names}')
            elif admiral_member:
                lines.append(f'**{label}:** {admiral_name}')
            # no holders and no admiral — omit this role line entirely

        embed.add_field(name=f'[{tag}]', value='\n'.join(lines), inline=False)

    embed.set_footer(text=f'Last updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}')
    return embed

# ---------------------------------------------------------------------------
# Approval view builder (shared)
# ---------------------------------------------------------------------------

def _build_request_embed(
    interaction: discord.Interaction,
    role: discord.Role,
    tag: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(title='Role Assignment Request', color=discord.Color.orange())
    embed.add_field(
        name='User',
        value=f'{interaction.user.mention} (`{interaction.user}`, ID: `{interaction.user.id}`)',
        inline=False,
    )
    embed.add_field(name='Requested Role', value=f'**{role.name}** (ID: `{role.id}`)', inline=False)
    if tag:
        embed.add_field(name='Alliance', value=f'`{tag}`', inline=True)
    embed.set_footer(text=f'Server: {interaction.guild.name}')
    return embed


def _build_approval_view(
    requester_id: int,
    role_id: int,
    *,
    channel_based: bool = False,
    disabled: bool = False,
) -> discord.ui.View:
    prefix = 'worf:ch_' if channel_based else 'worf:'
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label='Approve',
        style=discord.ButtonStyle.success,
        custom_id=f'{prefix}approve:{requester_id}:{role_id}',
        disabled=disabled,
    ))
    view.add_item(discord.ui.Button(
        label='Deny',
        style=discord.ButtonStyle.danger,
        custom_id=f'{prefix}deny:{requester_id}:{role_id}',
        disabled=disabled,
    ))
    return view

# ---------------------------------------------------------------------------
# Alliance modal
# ---------------------------------------------------------------------------

class AllianceModal(discord.ui.Modal, title='Update Alliance & In-Game Name'):
    ingame_name = discord.ui.TextInput(
        label='In-Game Name',
        placeholder='Enter your in-game name...',
        required=True,
        max_length=32,
    )
    alliance_tag = discord.ui.TextInput(
        label='Alliance Tag (4 letters, A-Z only)',
        placeholder='e.g. TREK',
        required=True,
        min_length=4,
        max_length=4,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        tag = self.alliance_tag.value.upper().strip()
        name = self.ingame_name.value.strip()

        if not re.match(r'^[A-Z]{4}$', tag):
            await interaction.response.send_message(
                'Invalid alliance tag. Must be exactly 4 letters A-Z with no numbers or special characters.',
                ephemeral=True,
            )
            return

        guild = interaction.guild
        member = interaction.user
        new_nick = f'[{tag}] {name}'

        try:
            await member.edit(nick=new_nick)
        except discord.Forbidden:
            await interaction.response.send_message(
                'I do not have permission to update your nickname. Please contact an administrator.',
                ephemeral=True,
            )
            return

        role = discord.utils.get(guild.roles, name=tag)
        if role is None:
            try:
                role = await guild.create_role(
                    name=tag,
                    reason='Auto-created alliance role via self-service',
                )
                logger.info('Created new alliance role: %s', tag)
            except discord.Forbidden:
                await interaction.response.send_message(
                    f'Nickname updated to `{new_nick}`, but I could not create the `{tag}` alliance role. '
                    'Please contact an administrator.',
                    ephemeral=True,
                )
                return

        try:
            await member.add_roles(role, reason=f'Alliance self-assignment: {tag}')
        except discord.Forbidden:
            await interaction.response.send_message(
                f'Nickname updated to `{new_nick}`, but I could not assign the `{tag}` role. '
                'Please contact an administrator.',
                ephemeral=True,
            )
            return

        state = load_state()
        if tag not in state.setdefault('alliances', []):
            state['alliances'].append(tag)
            save_state(state)

        if SERVER_ROLE_ID:
            server_role = guild.get_role(SERVER_ROLE_ID)
            if server_role is None:
                logger.warning('SERVER_ROLE_ID %s not found', SERVER_ROLE_ID)
            elif server_role not in member.roles:
                try:
                    await member.add_roles(server_role, reason='Server member role via self-service')
                except discord.Forbidden:
                    logger.warning('Cannot assign server role to %s', member)

        await interaction.response.send_message(
            f'Done! Your nickname is now `{new_nick}` and you have been added to the **{tag}** alliance.',
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.exception('Error in AllianceModal: %s', error)
        await interaction.response.send_message(
            'An unexpected error occurred. Please try again or contact an administrator.',
            ephemeral=True,
        )

# ---------------------------------------------------------------------------
# Admiral management modals
# ---------------------------------------------------------------------------

class RemoveRoleModal(discord.ui.Modal, title='Remove Role from Member'):
    target_name = discord.ui.TextInput(
        label="Member's name (without alliance tag)",
        placeholder='e.g. Thunder',
        required=True,
        max_length=64,
    )
    role_input = discord.ui.TextInput(
        label='Role to remove',
        placeholder='Commodore / First Officer / RoE Officer / Diplomacy Officer',
        required=True,
        max_length=32,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        name = self.target_name.value.strip()
        raw_role = self.role_input.value.strip().lower()

        role_key = ROLE_NAME_MAP.get(raw_role)
        if role_key is None:
            await interaction.response.send_message(
                f'Unknown role `{self.role_input.value}`. '
                'Valid options: **Commodore**, **First Officer**, **RoE Officer**, **Diplomacy Officer**.',
                ephemeral=True,
            )
            return

        role_id = ROLE_IDS.get(role_key, 0)
        if not role_id:
            await interaction.response.send_message(
                'That role is not configured on this bot. Contact an administrator.',
                ephemeral=True,
            )
            return

        role = guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message(
                'That role does not exist on this server. Contact an administrator.',
                ephemeral=True,
            )
            return

        target = find_member_by_name(guild, name)
        if target is None:
            await interaction.response.send_message(
                f'Could not find a member named `{name}`. Check the spelling (without the alliance tag).',
                ephemeral=True,
            )
            return

        ok, reason = verify_requester(interaction.user, target, guild)
        if not ok:
            await interaction.response.send_message(reason, ephemeral=True)
            return

        if role not in target.roles:
            await interaction.response.send_message(
                f'{target.mention} does not have the **{role.name}** role.',
                ephemeral=True,
            )
            return

        try:
            await target.remove_roles(role, reason=f'Removed by {interaction.user}')
            await interaction.response.send_message(
                f'**{role.name}** has been removed from {target.mention}.',
                ephemeral=True,
            )
            logger.info('%s removed %s from %s', interaction.user, role.name, target)
            try:
                await interaction.client.update_role_list_post(guild)
            except Exception:
                logger.exception('Failed to update role list after role removal')
        except discord.Forbidden:
            await interaction.response.send_message(
                f'I do not have permission to remove **{role.name}** from {target.mention}. '
                'Check the bot role hierarchy.',
                ephemeral=True,
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.exception('Error in RemoveRoleModal: %s', error)
        await interaction.response.send_message(
            'An unexpected error occurred. Please try again.',
            ephemeral=True,
        )


class RemovePlayerModal(discord.ui.Modal, title='Remove Player from Alliance'):
    target_name = discord.ui.TextInput(
        label="Member's name (without alliance tag)",
        placeholder='e.g. Thunder',
        required=True,
        max_length=64,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        name = self.target_name.value.strip()

        target = find_member_by_name(guild, name)
        if target is None:
            await interaction.response.send_message(
                f'Could not find a member named `{name}`. Check the spelling (without the alliance tag).',
                ephemeral=True,
            )
            return

        ok, reason = verify_requester(interaction.user, target, guild)
        if not ok:
            await interaction.response.send_message(reason, ephemeral=True)
            return

        target_tag = get_alliance_tag(target)

        # Collect every alliance/rank role to strip
        roles_to_remove: list[discord.Role] = []

        if target_tag:
            alliance_role = discord.utils.get(guild.roles, name=target_tag)
            if alliance_role and alliance_role in target.roles:
                roles_to_remove.append(alliance_role)

        for role_key in ('admiral', 'commodore', 'first_officer', 'roe_officer', 'diplomacy_officer'):
            rid = ROLE_IDS.get(role_key, 0)
            if rid:
                r = guild.get_role(rid)
                if r and r in target.roles:
                    roles_to_remove.append(r)

        if not roles_to_remove:
            await interaction.response.send_message(
                f'{target.mention} has no alliance or rank roles to remove.',
                ephemeral=True,
            )
            return

        try:
            await target.remove_roles(*roles_to_remove, reason=f'Removed from alliance by {interaction.user}')

            # Strip the [TAG] prefix from their nickname
            if target.nick:
                bare = strip_alliance_tag(target.nick)
                try:
                    await target.edit(nick=bare or None)
                except discord.Forbidden:
                    pass

            # If this member was a registered admiral, remove from state
            if target_tag:
                state = load_state()
                if state.get('admirals', {}).get(target_tag) == target.id:
                    del state['admirals'][target_tag]
                    save_state(state)
                    logger.info('Removed %s from admiral registry for %s', target, target_tag)

            removed_names = ', '.join(f'**{r.name}**' for r in roles_to_remove)
            await interaction.response.send_message(
                f'{target.mention} has been removed from alliance `{target_tag}`. '
                f'Stripped roles: {removed_names}.',
                ephemeral=True,
            )
            logger.info('%s removed %s from alliance %s', interaction.user, target, target_tag)
            try:
                await interaction.client._cleanup_empty_alliances(guild)
                await interaction.client.update_role_list_post(guild)
            except Exception:
                logger.exception('Failed to update role list after player removal')

        except discord.Forbidden:
            await interaction.response.send_message(
                f'I do not have permission to remove roles from {target.mention}. '
                'Check the bot role hierarchy.',
                ephemeral=True,
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.exception('Error in RemovePlayerModal: %s', error)
        await interaction.response.send_message(
            'An unexpected error occurred. Please try again.',
            ephemeral=True,
        )

# ---------------------------------------------------------------------------
# Role request routing
# ---------------------------------------------------------------------------

async def send_role_request(interaction: discord.Interaction, role_key: str) -> None:
    role_id = ROLE_IDS[role_key]
    guild = interaction.guild

    if not role_id:
        await interaction.response.send_message(
            'This role has not been configured yet. Please contact an administrator.',
            ephemeral=True,
        )
        return

    role = guild.get_role(role_id)
    if role is None:
        await interaction.response.send_message(
            'The requested role could not be found on this server. Please contact an administrator.',
            ephemeral=True,
        )
        logger.warning('Role ID %s for key %r not found in guild', role_id, role_key)
        return

    admin_channel = interaction.client.get_channel(ADMIN_REQUEST_CHANNEL_ID)
    admin_role = guild.get_role(ADMIN_ROLE_ID) if ADMIN_ROLE_ID else None
    admin_mention = admin_role.mention if admin_role else '**Admins**'

    use_leadership_channel = False
    admiral_member = None
    tag = None
    category = None
    leadership_fallback_reason = ''

    if role_key in LEADERSHIP_ROLES:
        tag = get_alliance_tag(interaction.user)
        if not tag:
            leadership_fallback_reason = 'user has no alliance tag'
        else:
            state = load_state()
            admiral_id = state.get('admirals', {}).get(tag)
            if not admiral_id:
                leadership_fallback_reason = f'no admiral registered for `{tag}`'
            else:
                admiral_member = guild.get_member(admiral_id)
                if not admiral_member:
                    leadership_fallback_reason = f'admiral for `{tag}` has left the server'
                elif not LEADERSHIP_CATEGORY_ID:
                    leadership_fallback_reason = 'LEADERSHIP_CATEGORY_ID not configured'
                else:
                    category = guild.get_channel(LEADERSHIP_CATEGORY_ID)
                    if not isinstance(category, discord.CategoryChannel):
                        leadership_fallback_reason = 'leadership category not found or wrong type'
                    else:
                        use_leadership_channel = True

    if use_leadership_channel:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_channels=True
            ),
            admiral_member: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        channel_name = f'req-{tag.lower()}-{str(interaction.user.id)[-6:]}'

        try:
            temp_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f'Role request: {role.name} for {interaction.user}',
            )
        except discord.Forbidden:
            logger.warning('Cannot create leadership channel; falling back to admin channel')
            leadership_fallback_reason = 'bot lacks permission to create the approval channel'
        else:
            await interaction.response.send_message(
                f'Your request for **{role.name}** has been sent to your alliance admiral for review.',
                ephemeral=True,
            )
            embed = _build_request_embed(interaction, role, tag=tag)
            view = _build_approval_view(interaction.user.id, role.id, channel_based=True)
            await temp_channel.send(
                content=f'{admiral_member.mention} {admin_mention} — role request for alliance **{tag}**:',
                embed=embed,
                view=view,
            )
            logger.info(
                'Leadership channel %s created for %s requesting %s',
                channel_name, interaction.user, role.name,
            )
            return

    if admin_channel is None:
        await interaction.response.send_message(
            'The admin review channel is not reachable. Please contact an administrator directly.',
            ephemeral=True,
        )
        return

    reason_suffix = f' *({leadership_fallback_reason})*' if leadership_fallback_reason else ''

    await interaction.response.send_message(
        f'Your request for **{role.name}** is under review. An administrator will action it shortly.',
        ephemeral=True,
    )
    embed = _build_request_embed(interaction, role, tag=tag)
    view = _build_approval_view(interaction.user.id, role.id, channel_based=False)
    await admin_channel.send(
        content=f'{admin_mention} — new role request{reason_suffix}:',
        embed=embed,
        view=view,
    )
    logger.info('Role request for %s from %s posted to admin channel', role.name, interaction.user)

# ---------------------------------------------------------------------------
# Persistent views
# ---------------------------------------------------------------------------

class SelfServiceView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label='Change Alliance & In-Game Name',
        style=discord.ButtonStyle.primary,
        custom_id='worf:change_alliance',
        row=0,
    )
    async def change_alliance(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(AllianceModal())

    @discord.ui.button(
        label='Request Admiral Access',
        style=discord.ButtonStyle.success,
        custom_id='worf:req_admiral',
        row=1,
    )
    async def req_admiral(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await send_role_request(interaction, 'admiral')

    @discord.ui.button(
        label='Request Commodore Access',
        style=discord.ButtonStyle.success,
        custom_id='worf:req_commodore',
        row=1,
    )
    async def req_commodore(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await send_role_request(interaction, 'commodore')

    @discord.ui.button(
        label='Request First-Officer Access',
        style=discord.ButtonStyle.success,
        custom_id='worf:req_first_officer',
        row=2,
    )
    async def req_first_officer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await send_role_request(interaction, 'first_officer')

    @discord.ui.button(
        label='Request RoE Officer Access',
        style=discord.ButtonStyle.success,
        custom_id='worf:req_roe_officer',
        row=2,
    )
    async def req_roe_officer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await send_role_request(interaction, 'roe_officer')

    @discord.ui.button(
        label='Request Diplomacy Officer Access',
        style=discord.ButtonStyle.success,
        custom_id='worf:req_diplomacy_officer',
        row=3,
    )
    async def req_diplomacy_officer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await send_role_request(interaction, 'diplomacy_officer')


class AdmiralManagementView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label='Remove Role',
        style=discord.ButtonStyle.danger,
        custom_id='worf:mgmt_remove_role',
        row=0,
    )
    async def remove_role(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RemoveRoleModal())

    @discord.ui.button(
        label='Remove Player from Alliance',
        style=discord.ButtonStyle.danger,
        custom_id='worf:mgmt_remove_player',
        row=0,
    )
    async def remove_player(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RemovePlayerModal())

# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class WorfBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix='!worf ', intents=intents)
        self._register_commands()

    # ── Role roster ─────────────────────────────────────────────────────────

    async def update_role_list_post(self, guild: discord.Guild) -> None:
        state = load_state()
        channel_id = state.get('role_list_channel_id')
        if not channel_id:
            return

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            logger.warning('Role list channel %s not found', channel_id)
            return

        embed = generate_role_list_embed(guild, state)
        message_id = state.get('role_list_message_id')

        if message_id:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.edit(embed=embed)
                logger.info('Role list post updated')
                return
            except discord.NotFound:
                logger.warning('Role list message not found; creating new post')
            except discord.HTTPException as exc:
                logger.warning('Could not edit role list post: %s', exc)

        msg = await channel.send(embed=embed)
        state['role_list_message_id'] = msg.id
        save_state(state)
        logger.info('Role list post created (message ID: %s)', msg.id)

    # ── Alliance cleanup ────────────────────────────────────────────────────

    async def _cleanup_empty_alliances(self, guild: discord.Guild) -> bool:
        """
        Remove any registered alliance whose role has zero members.
        Deletes the Discord role and removes the entry from state.
        Returns True if anything was changed.
        """
        state = load_state()
        alliances: list[str] = state.get('alliances', [])
        admirals_map: dict = state.get('admirals', {})

        to_remove: list[str] = []
        for tag in alliances:
            alliance_role = discord.utils.get(guild.roles, name=tag)
            if alliance_role is None or len(alliance_role.members) == 0:
                to_remove.append(tag)

        if not to_remove:
            return False

        for tag in to_remove:
            alliances.remove(tag)
            admirals_map.pop(tag, None)
            alliance_role = discord.utils.get(guild.roles, name=tag)
            if alliance_role is not None:
                try:
                    await alliance_role.delete(reason='Auto-removed: alliance has no remaining members')
                    logger.info('Deleted empty alliance role %s', tag)
                except discord.Forbidden:
                    logger.warning('Cannot delete empty alliance role %s — insufficient permissions', tag)

        state['alliances'] = alliances
        state['admirals'] = admirals_map
        save_state(state)
        logger.info('Removed empty alliances: %s', to_remove)
        return True

    @tasks.loop(hours=1.0)
    async def _alliance_cleanup_task(self) -> None:
        for guild in self.guilds:
            try:
                changed = await self._cleanup_empty_alliances(guild)
                if changed:
                    await self.update_role_list_post(guild)
            except Exception:
                logger.exception('Periodic alliance cleanup failed for guild %s', guild.id)

    @_alliance_cleanup_task.before_loop
    async def _before_alliance_cleanup(self) -> None:
        await self.wait_until_ready()

    async def on_member_remove(self, member: discord.Member) -> None:
        # If this member was a registered admiral, clear them from state immediately
        tag = get_alliance_tag(member)
        if tag:
            state = load_state()
            if state.get('admirals', {}).get(tag) == member.id:
                del state['admirals'][tag]
                save_state(state)
                logger.info('Removed departed admiral %s from registry for %s', member, tag)

        # Check whether any alliance is now empty
        try:
            changed = await self._cleanup_empty_alliances(member.guild)
            if changed:
                await self.update_role_list_post(member.guild)
        except Exception:
            logger.exception('Alliance cleanup failed after member leave: %s', member)

    # ── Slash commands ──────────────────────────────────────────────────────

    def _register_commands(self) -> None:

        @self.tree.command(
            name='addalliance',
            description='Register an existing alliance tag so the bot is aware of it.',
        )
        @app_commands.describe(tag='The 4-letter alliance tag (A-Z only)')
        async def addalliance(interaction: discord.Interaction, tag: str) -> None:
            if interaction.channel_id != ADMIN_REQUEST_CHANNEL_ID:
                await interaction.response.send_message(
                    'This command can only be used in the designated admin channel.', ephemeral=True
                )
                return

            tag = tag.upper().strip()
            if not re.match(r'^[A-Z]{4}$', tag):
                await interaction.response.send_message(
                    'Invalid tag. Must be exactly 4 letters A-Z.', ephemeral=True
                )
                return

            role = discord.utils.get(interaction.guild.roles, name=tag)
            if role is None:
                await interaction.response.send_message(
                    f'No role named `{tag}` exists on this server. Create the role first.',
                    ephemeral=True,
                )
                return

            state = load_state()
            alliances = state.setdefault('alliances', [])
            if tag in alliances:
                await interaction.response.send_message(
                    f'Alliance `{tag}` is already registered.', ephemeral=True
                )
                return

            alliances.append(tag)
            save_state(state)
            await interaction.response.send_message(f'Alliance **{tag}** has been registered.')
            logger.info('%s registered alliance %s', interaction.user, tag)
            try:
                await self.update_role_list_post(interaction.guild)
            except Exception:
                logger.exception('Failed to update role list after /addalliance')

        @self.tree.command(
            name='addadmiral',
            description='Register an existing member as admiral of an alliance.',
        )
        @app_commands.describe(
            tag='The 4-letter alliance tag',
            user='The member to register as admiral',
        )
        async def addadmiral(
            interaction: discord.Interaction, tag: str, user: discord.Member
        ) -> None:
            if interaction.channel_id != ADMIN_REQUEST_CHANNEL_ID:
                await interaction.response.send_message(
                    'This command can only be used in the designated admin channel.', ephemeral=True
                )
                return

            tag = tag.upper().strip()
            if not re.match(r'^[A-Z]{4}$', tag):
                await interaction.response.send_message(
                    'Invalid tag. Must be exactly 4 letters A-Z.', ephemeral=True
                )
                return

            state = load_state()
            if tag not in state.get('alliances', []):
                await interaction.response.send_message(
                    f'Alliance `{tag}` is not registered. Run `/addalliance {tag}` first.',
                    ephemeral=True,
                )
                return

            admiral_role_id = ROLE_IDS.get('admiral', 0)
            if admiral_role_id:
                admiral_role = interaction.guild.get_role(admiral_role_id)
                if admiral_role and admiral_role not in user.roles:
                    await interaction.response.send_message(
                        f'{user.mention} does not have the Admiral role. Assign it first.',
                        ephemeral=True,
                    )
                    return

            state.setdefault('admirals', {})[tag] = user.id
            save_state(state)
            await interaction.response.send_message(
                f'{user.mention} has been registered as Admiral of alliance **{tag}**.'
            )
            logger.info('%s registered %s as admiral of %s', interaction.user, user, tag)
            try:
                await self.update_role_list_post(interaction.guild)
            except Exception:
                logger.exception('Failed to update role list after /addadmiral')

        @self.tree.command(
            name='listadmirals',
            description='Show all registered admirals and their alliance tags.',
        )
        async def listadmirals(interaction: discord.Interaction) -> None:
            if interaction.channel_id != ADMIN_REQUEST_CHANNEL_ID:
                await interaction.response.send_message(
                    'This command can only be used in the designated admin channel.', ephemeral=True
                )
                return

            state = load_state()
            admirals = state.get('admirals', {})

            if not admirals:
                await interaction.response.send_message(
                    'No admirals are currently registered.', ephemeral=True
                )
                return

            embed = discord.Embed(title='Admiral Roster', color=discord.Color.blue())
            lines = []
            for atag, uid in sorted(admirals.items()):
                member = interaction.guild.get_member(uid)
                display = member.mention if member else f'*(left server — ID: {uid})*'
                lines.append(f'**{atag}** — {display}')
            embed.description = '\n'.join(lines)
            await interaction.response.send_message(embed=embed)

        @self.tree.command(
            name='setrolelist',
            description='Set the channel where the alliance role roster is maintained.',
        )
        @app_commands.describe(channel='Channel where the role list will be posted and kept updated')
        async def setrolelist(
            interaction: discord.Interaction, channel: discord.TextChannel
        ) -> None:
            if interaction.channel_id != ADMIN_REQUEST_CHANNEL_ID:
                await interaction.response.send_message(
                    'This command can only be used in the designated admin channel.', ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=False)

            state = load_state()
            old_channel_id = state.get('role_list_channel_id')
            old_message_id = state.get('role_list_message_id')

            # Remove old post if it exists
            if old_channel_id and old_message_id:
                old_ch = interaction.guild.get_channel(int(old_channel_id))
                if old_ch:
                    try:
                        old_msg = await old_ch.fetch_message(int(old_message_id))
                        await old_msg.delete()
                        logger.info('Deleted old role list post from channel %s', old_channel_id)
                    except (discord.NotFound, discord.Forbidden):
                        pass

            state['role_list_channel_id'] = channel.id
            state.pop('role_list_message_id', None)
            save_state(state)

            try:
                await self.update_role_list_post(interaction.guild)
                await interaction.followup.send(
                    f'Alliance role roster is now being maintained in {channel.mention}.'
                )
            except Exception:
                logger.exception('Failed to post role list to new channel')
                await interaction.followup.send(
                    f'Channel set to {channel.mention}, but I could not post the roster. '
                    'Check my permissions in that channel.',
                    ephemeral=True,
                )
            logger.info('%s set role list channel to %s', interaction.user, channel)

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def setup_hook(self) -> None:
        self.add_view(SelfServiceView())
        self.add_view(AdmiralManagementView())
        self._alliance_cleanup_task.start()
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild_obj)
            await self.tree.sync(guild=guild_obj)
            logger.info('Slash commands synced to guild %s (instant)', GUILD_ID)
        else:
            await self.tree.sync()
            logger.info('Slash commands synced globally (may take up to 1 hour to appear)')

    async def on_ready(self) -> None:
        logger.info('Worf is online: %s (ID: %s)', self.user, self.user.id)
        await self._post_or_update_self_service()
        await self._post_or_update_admiral_management()

    # ── Interaction routing ─────────────────────────────────────────────────

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if (
            interaction.type == discord.InteractionType.component
            and interaction.data is not None
        ):
            custom_id = interaction.data.get('custom_id', '')
            if any(custom_id.startswith(p) for p in APPROVAL_PREFIXES):
                try:
                    await self._handle_role_decision(interaction)
                except Exception:
                    logger.exception('Unhandled error in role decision handler')
                    try:
                        await interaction.response.send_message(
                            'An unexpected error occurred. Please contact a developer.',
                            ephemeral=True,
                        )
                    except Exception:
                        pass
                return

        await super().on_interaction(interaction)

    async def _handle_role_decision(self, interaction: discord.Interaction) -> None:
        custom_id = interaction.data['custom_id']
        channel_based = custom_id.startswith('worf:ch_')

        inner = custom_id[len('worf:ch_'):] if channel_based else custom_id[len('worf:'):]
        parts = inner.split(':', 2)
        if len(parts) != 3:
            await interaction.response.send_message(
                'Malformed interaction data. Please contact a developer.', ephemeral=True
            )
            return

        action, requester_id_str, role_id_str = parts
        requester_id = int(requester_id_str)
        role_id = int(role_id_str)
        approved = action == 'approve'

        guild = interaction.guild
        member = guild.get_member(requester_id)
        role = guild.get_role(role_id)
        disabled_view = _build_approval_view(
            requester_id, role_id, channel_based=channel_based, disabled=True
        )
        channel_note = ' *(This channel will be deleted in 10 s.)*' if channel_based else ''

        async def cleanup() -> None:
            if channel_based:
                await asyncio.sleep(10)
                try:
                    await interaction.channel.delete(reason='Role request processed')
                except Exception:
                    logger.warning('Could not delete leadership channel %s', interaction.channel)

        if approved:
            if member is None:
                await interaction.response.edit_message(view=disabled_view)
                await interaction.followup.send(
                    f'Could not locate user (ID: `{requester_id}`) — they may have left the server. '
                    f'Role was not assigned.{channel_note}'
                )
                await cleanup()
                return

            if role is None:
                await interaction.response.edit_message(view=disabled_view)
                await interaction.followup.send(
                    f'Error: Role ID `{role_id}` no longer exists on this server.{channel_note}'
                )
                await cleanup()
                return

            try:
                await member.add_roles(role, reason=f'Approved by {interaction.user}')

                # Record admiral assignment automatically
                if role_id == ROLE_IDS.get('admiral', 0):
                    atag = get_alliance_tag(member)
                    if atag:
                        state = load_state()
                        state.setdefault('admirals', {})[atag] = member.id
                        if atag not in state.setdefault('alliances', []):
                            state['alliances'].append(atag)
                        save_state(state)
                        logger.info('Recorded %s as admiral of %s', member, atag)

                await interaction.response.edit_message(view=disabled_view)
                await interaction.followup.send(
                    f'Role **{role.name}** has been granted to {member.mention}. '
                    f'Approved by {interaction.user.mention}.{channel_note}'
                )
                logger.info('%s approved %s for %s', interaction.user, role.name, member)

                try:
                    await self.update_role_list_post(guild)
                except Exception:
                    logger.exception('Failed to update role list after approval')

            except discord.Forbidden:
                await interaction.response.edit_message(view=disabled_view)
                await interaction.followup.send(
                    f'Error: I do not have permission to assign **{role.name}** to {member.mention}. '
                    f'Check the bot role hierarchy.{channel_note}'
                )

            await cleanup()

        else:
            member_mention = member.mention if member else f'User ID `{requester_id}`'
            role_display = f'**{role.name}**' if role else f'role ID `{role_id}`'
            await interaction.response.edit_message(view=disabled_view)
            await interaction.followup.send(
                f'Role request for {role_display} from {member_mention} was denied by '
                f'{interaction.user.mention}.{channel_note}'
            )
            logger.info('%s denied role ID %s for user ID %s', interaction.user, role_id, requester_id)
            await cleanup()

    # ── Panel posts ─────────────────────────────────────────────────────────

    async def _post_or_update_self_service(self) -> None:
        channel = self.get_channel(SELF_SERVICE_CHANNEL_ID)
        if channel is None:
            logger.error('Self-service channel ID %s not found.', SELF_SERVICE_CHANNEL_ID)
            return

        state = load_state()
        message_id = state.get('self_service_message_id')

        embed = discord.Embed(
            title='Server Self Service',
            description='Please choose the option you wish to complete!',
            color=discord.Color.dark_blue(),
        )
        view = SelfServiceView()

        if message_id:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.edit(embed=embed, view=view)
                logger.info('Self-service post updated (message ID: %s)', message_id)
                return
            except discord.NotFound:
                logger.warning('Stored self-service message not found; creating new post.')
            except discord.HTTPException as exc:
                logger.warning('Could not edit self-service message: %s', exc)

        msg = await channel.send(embed=embed, view=view)
        state['self_service_message_id'] = msg.id
        save_state(state)
        logger.info('Self-service post created (message ID: %s)', msg.id)

    async def _post_or_update_admiral_management(self) -> None:
        if not ADMIRAL_MANAGEMENT_CHANNEL_ID:
            return

        channel = self.get_channel(ADMIRAL_MANAGEMENT_CHANNEL_ID)
        if channel is None:
            logger.warning('Admiral management channel %s not found.', ADMIRAL_MANAGEMENT_CHANNEL_ID)
            return

        state = load_state()
        message_id = state.get('admiral_management_message_id')

        embed = discord.Embed(
            title='Alliance Management',
            description=(
                'Use the buttons below to manage alliance members and roles.\n\n'
                '**Remove Role** — remove a rank from a member in your alliance.\n'
                '**Remove Player** — fully remove a member from your alliance, '
                'stripping all roles and their alliance tag.'
            ),
            color=discord.Color.dark_red(),
        )
        view = AdmiralManagementView()

        if message_id:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.edit(embed=embed, view=view)
                logger.info('Admiral management post updated (message ID: %s)', message_id)
                return
            except discord.NotFound:
                logger.warning('Stored admiral management message not found; creating new post.')
            except discord.HTTPException as exc:
                logger.warning('Could not edit admiral management message: %s', exc)

        msg = await channel.send(embed=embed, view=view)
        state['admiral_management_message_id'] = msg.id
        save_state(state)
        logger.info('Admiral management post created (message ID: %s)', msg.id)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    missing = [
        name
        for name, val in [
            ('DISCORD_TOKEN', DISCORD_TOKEN),
            ('SELF_SERVICE_CHANNEL_ID', os.getenv('SELF_SERVICE_CHANNEL_ID')),
            ('ADMIN_REQUEST_CHANNEL_ID', os.getenv('ADMIN_REQUEST_CHANNEL_ID')),
        ]
        if not val
    ]
    if missing:
        logger.error('Missing required environment variables: %s', ', '.join(missing))
        raise SystemExit(1)

    bot = WorfBot()
    bot.run(DISCORD_TOKEN)


if __name__ == '__main__':
    main()
