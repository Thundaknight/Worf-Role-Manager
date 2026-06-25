import discord
from discord.ext import commands
import os
import json
import re
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('worf')

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
SELF_SERVICE_CHANNEL_ID = int(os.getenv('SELF_SERVICE_CHANNEL_ID', '0'))
ADMIN_REQUEST_CHANNEL_ID = int(os.getenv('ADMIN_REQUEST_CHANNEL_ID', '0'))

SERVER_ROLE_ID = int(os.getenv('SERVER_ROLE_ID', '0'))

ROLE_NAMES = {
    'admiral': os.getenv('ADMIRAL_ROLE_NAME', 'Admiral'),
    'commodore': os.getenv('COMMODORE_ROLE_NAME', 'Commodore'),
    'first_officer': os.getenv('FIRST_OFFICER_ROLE_NAME', 'First Officer'),
    'roe_officer': os.getenv('ROE_OFFICER_ROLE_NAME', 'RoE Officer'),
    'diplomacy_officer': os.getenv('DIPLOMACY_OFFICER_ROLE_NAME', 'Diplomacy Officer'),
}

STATE_FILE = '/data/bot_state.json'


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
                "Invalid alliance tag. Must be exactly 4 letters A-Z with no numbers or special characters.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        member = interaction.user
        new_nick = f"[{tag}] {name}"

        try:
            await member.edit(nick=new_nick)
        except discord.Forbidden:
            await interaction.response.send_message(
                "I do not have permission to update your nickname. Please contact an administrator.",
                ephemeral=True,
            )
            return

        role = discord.utils.get(guild.roles, name=tag)
        if role is None:
            try:
                role = await guild.create_role(
                    name=tag,
                    reason="Auto-created alliance role via self-service",
                )
                logger.info("Created new alliance role: %s", tag)
            except discord.Forbidden:
                await interaction.response.send_message(
                    f"Nickname updated to `{new_nick}`, but I could not create the `{tag}` alliance role. "
                    "Please contact an administrator.",
                    ephemeral=True,
                )
                return

        try:
            await member.add_roles(role, reason=f"Alliance self-assignment: {tag}")
        except discord.Forbidden:
            await interaction.response.send_message(
                f"Nickname updated to `{new_nick}`, but I could not assign the `{tag}` role. "
                "Please contact an administrator.",
                ephemeral=True,
            )
            return

        # Assign the server-wide member role if configured and not already held.
        if SERVER_ROLE_ID:
            server_role = guild.get_role(SERVER_ROLE_ID)
            if server_role is None:
                logger.warning(
                    "SERVER_ROLE_ID %s not found in guild; skipping server role assignment.",
                    SERVER_ROLE_ID,
                )
            elif server_role not in member.roles:
                try:
                    await member.add_roles(server_role, reason="Server member role assigned via self-service")
                    logger.info("Assigned server role %s to %s", server_role.name, member)
                except discord.Forbidden:
                    logger.warning(
                        "No permission to assign server role %s to %s", server_role.name, member
                    )

        await interaction.response.send_message(
            f"Done! Your nickname is now `{new_nick}` and you have been added to the **{tag}** alliance.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.exception("Error in AllianceModal: %s", error)
        await interaction.response.send_message(
            "An unexpected error occurred. Please try again or contact an administrator.",
            ephemeral=True,
        )


async def send_role_request(interaction: discord.Interaction, role_key: str) -> None:
    role_name = ROLE_NAMES[role_key]
    admin_channel = interaction.client.get_channel(ADMIN_REQUEST_CHANNEL_ID)

    if admin_channel is None:
        await interaction.response.send_message(
            "The admin review channel is not reachable. Please contact an administrator directly.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"Your request for the **{role_name}** role is under review. "
        "An administrator will action it shortly.",
        ephemeral=True,
    )

    embed = discord.Embed(
        title="Role Assignment Request",
        color=discord.Color.orange(),
    )
    embed.add_field(
        name="User",
        value=f"{interaction.user.mention} (`{interaction.user}`, ID: `{interaction.user.id}`)",
        inline=False,
    )
    embed.add_field(name="Requested Role", value=f"**{role_name}**", inline=False)
    embed.set_footer(text=f"Server: {interaction.guild.name}")

    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label="Approve",
        style=discord.ButtonStyle.success,
        custom_id=f"worf:approve:{interaction.user.id}:{role_name}",
    ))
    view.add_item(discord.ui.Button(
        label="Deny",
        style=discord.ButtonStyle.danger,
        custom_id=f"worf:deny:{interaction.user.id}:{role_name}",
    ))

    await admin_channel.send(embed=embed, view=view)
    logger.info(
        "Role request posted for %s requesting %s", interaction.user, role_name
    )


class SelfServiceView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label='Change Alliance & In-Game Name',
        style=discord.ButtonStyle.primary,
        custom_id='worf:change_alliance',
        row=0,
    )
    async def change_alliance(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(AllianceModal())

    @discord.ui.button(
        label='Request Admiral Access',
        style=discord.ButtonStyle.success,
        custom_id='worf:req_admiral',
        row=1,
    )
    async def req_admiral(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await send_role_request(interaction, 'admiral')

    @discord.ui.button(
        label='Request Commodore Access',
        style=discord.ButtonStyle.success,
        custom_id='worf:req_commodore',
        row=1,
    )
    async def req_commodore(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await send_role_request(interaction, 'commodore')

    @discord.ui.button(
        label='Request First-Officer Access',
        style=discord.ButtonStyle.success,
        custom_id='worf:req_first_officer',
        row=2,
    )
    async def req_first_officer(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await send_role_request(interaction, 'first_officer')

    @discord.ui.button(
        label='Request RoE Officer Access',
        style=discord.ButtonStyle.success,
        custom_id='worf:req_roe_officer',
        row=2,
    )
    async def req_roe_officer(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await send_role_request(interaction, 'roe_officer')

    @discord.ui.button(
        label='Request Diplomacy Officer Access',
        style=discord.ButtonStyle.success,
        custom_id='worf:req_diplomacy_officer',
        row=3,
    )
    async def req_diplomacy_officer(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await send_role_request(interaction, 'diplomacy_officer')


def _build_disabled_approval_view(requester_id: int, role_name: str) -> discord.ui.View:
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="Approve",
        style=discord.ButtonStyle.success,
        custom_id=f"worf:approve:{requester_id}:{role_name}",
        disabled=True,
    ))
    view.add_item(discord.ui.Button(
        label="Deny",
        style=discord.ButtonStyle.danger,
        custom_id=f"worf:deny:{requester_id}:{role_name}",
        disabled=True,
    ))
    return view


class WorfBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix='!worf ', intents=intents)

    async def setup_hook(self) -> None:
        self.add_view(SelfServiceView())

    async def on_ready(self) -> None:
        logger.info("Worf is online: %s (ID: %s)", self.user, self.user.id)
        await self._post_or_update_self_service()

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if (
            interaction.type == discord.InteractionType.component
            and interaction.data is not None
        ):
            custom_id = interaction.data.get('custom_id', '')
            if custom_id.startswith('worf:approve:') or custom_id.startswith('worf:deny:'):
                try:
                    await self._handle_role_decision(interaction)
                except Exception:
                    logger.exception("Unhandled error in role decision handler")
                    try:
                        await interaction.response.send_message(
                            "An unexpected error occurred. Please contact a developer.",
                            ephemeral=True,
                        )
                    except Exception:
                        pass
                return

        await super().on_interaction(interaction)

    async def _handle_role_decision(self, interaction: discord.Interaction) -> None:
        custom_id = interaction.data['custom_id']
        # Format: worf:approve:<user_id>:<role_name>  (role_name may contain colons)
        parts = custom_id.split(':', 3)

        if len(parts) != 4:
            await interaction.response.send_message(
                "Malformed interaction data. Please contact a developer.", ephemeral=True
            )
            return

        _, action, requester_id_str, role_name = parts
        requester_id = int(requester_id_str)
        approved = action == 'approve'

        disabled_view = _build_disabled_approval_view(requester_id, role_name)
        guild = interaction.guild
        member = guild.get_member(requester_id)

        if approved:
            if member is None:
                await interaction.response.edit_message(view=disabled_view)
                await interaction.followup.send(
                    f"Could not locate user (ID: `{requester_id}`) — they may have left the server. "
                    f"Role **{role_name}** was not assigned."
                )
                return

            role = discord.utils.get(guild.roles, name=role_name)
            if role is None:
                await interaction.response.edit_message(view=disabled_view)
                await interaction.followup.send(
                    f"Error: Role **{role_name}** does not exist on this server. "
                    "Please create it and process this request again."
                )
                return

            try:
                await member.add_roles(role, reason=f"Role approved by {interaction.user}")
                await interaction.response.edit_message(view=disabled_view)
                await interaction.followup.send(
                    f"Role **{role_name}** has been granted to {member.mention}. "
                    f"Approved by {interaction.user.mention}."
                )
                logger.info(
                    "%s approved %s for %s", interaction.user, role_name, member
                )
            except discord.Forbidden:
                await interaction.response.edit_message(view=disabled_view)
                await interaction.followup.send(
                    f"Error: I do not have permission to assign **{role_name}** to {member.mention}. "
                    "Ensure the Worf bot role is above this role in the server role hierarchy."
                )
        else:
            await interaction.response.edit_message(view=disabled_view)
            member_mention = member.mention if member else f"User ID `{requester_id}`"
            await interaction.followup.send(
                f"Role request for **{role_name}** from {member_mention} was denied by "
                f"{interaction.user.mention}."
            )
            logger.info(
                "%s denied %s for user ID %s", interaction.user, role_name, requester_id
            )

    async def _post_or_update_self_service(self) -> None:
        channel = self.get_channel(SELF_SERVICE_CHANNEL_ID)
        if channel is None:
            logger.error(
                "Self-service channel ID %s not found or not accessible. "
                "Check SELF_SERVICE_CHANNEL_ID and that the bot has access to that channel.",
                SELF_SERVICE_CHANNEL_ID,
            )
            return

        state = load_state()
        message_id = state.get('self_service_message_id')

        embed = discord.Embed(
            title="Server Self Service",
            description="Please choose the option you wish to complete!",
            color=discord.Color.dark_blue(),
        )
        view = SelfServiceView()

        if message_id:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.edit(embed=embed, view=view)
                logger.info("Self-service post updated (message ID: %s)", message_id)
                return
            except discord.NotFound:
                logger.warning(
                    "Stored self-service message ID %s no longer exists; creating a new post.",
                    message_id,
                )
            except discord.HTTPException as exc:
                logger.warning("Could not edit self-service message: %s", exc)

        msg = await channel.send(embed=embed, view=view)
        state['self_service_message_id'] = msg.id
        save_state(state)
        logger.info("Self-service post created (message ID: %s)", msg.id)


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
        logger.error("Missing required environment variables: %s", ', '.join(missing))
        raise SystemExit(1)

    bot = WorfBot()
    bot.run(DISCORD_TOKEN)


if __name__ == '__main__':
    main()
