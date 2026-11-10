"""Registration bot for the Lucky Clover guild. One process, no database."""

from __future__ import annotations

import os
import traceback

import discord
from discord import app_commands

REGISTER_BUTTON = "lc:register"
INITIATE = "Initiate"
SPEC_ROLES = ("Tank", "Heal", "DPS")
CLASSES = (
    ("Warrior", "Воин"),
    ("Paladin", "Паладин"),
    ("Hunter", "Охотник"),
    ("Rogue", "Разбойник"),
    ("Priest", "Жрец"),
    ("Shaman", "Шаман"),
    ("Mage", "Маг"),
    ("Warlock", "Чернокнижник"),
    ("Druid", "Друид"),
)
CLASS_NAMES = {name for name, _label in CLASSES}
MANAGED = CLASS_NAMES | set(SPEC_ROLES)
REASON = "Lucky Clover registration"
NO_MENTIONS = discord.AllowedMentions.none()
_SEPARATORS = " -'’"


def load_env(path: str) -> None:
    try:
        handle = open(path, encoding="utf-8")
    except OSError:
        return
    with handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def require_snowflake(name: str) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw.isdigit():
        raise SystemExit(f"{name} должен быть числовым ID Discord.")
    return int(raw)


load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("Нет DISCORD_TOKEN. Скопируй .env.example в .env и впиши токен.")
GUILD_ID = require_snowflake("GUILD_ID")
REG_CHANNEL_ID = require_snowflake("REG_CHANNEL_ID")
GUILD = discord.Object(id=GUILD_ID)


def clean_nick(raw: str) -> str | None:
    nick = " ".join(raw.split())
    if not 2 <= len(nick) <= 32:
        return None
    if not nick[0].isalpha() or not nick[-1].isalpha():
        return None
    previous_separator = False
    for char in nick:
        if char.isalpha():
            previous_separator = False
            continue
        if previous_separator or char not in _SEPARATORS:
            return None
        previous_separator = True
    return nick


def find_role(guild: discord.Guild, name: str) -> discord.Role | None:
    for role in guild.roles:
        if role.name == name:
            return role
    return None


def next_roles(member: discord.Member, chosen: list[discord.Role]) -> list[discord.Role]:
    chosen_ids = {role.id for role in chosen}
    roles: list[discord.Role] = []
    seen: set[int] = set()
    for role in member.roles:
        if role.is_default() or role.id in seen:
            continue
        if role.name in MANAGED and role.id not in chosen_ids:
            continue
        roles.append(role)
        seen.add(role.id)
    for role in chosen:
        if role.id not in seen:
            roles.append(role)
            seen.add(role.id)
    return roles


async def reply(interaction: discord.Interaction, content: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True, allowed_mentions=NO_MENTIONS)
        else:
            await interaction.response.send_message(
                content,
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
    except discord.HTTPException as exc:
        print(f"reply failed: {exc}", flush=True)


def is_admin(interaction: discord.Interaction) -> bool:
    permissions = interaction.permissions
    return permissions is not None and permissions.administrator


def panel_embed() -> discord.Embed:
    return discord.Embed(
        title="Добро пожаловать в гильдию!",
        description="Заполни анкету, чтобы открыть сервер.\nГильдия **Lucky Clover**.",
        colour=0x248046,
    )


def has_register_button(message: discord.Message) -> bool:
    for row in message.components:
        children = getattr(row, "children", None) or ()
        for child in children:
            if getattr(child, "custom_id", None) == REGISTER_BUTTON:
                return True
        if getattr(row, "custom_id", None) == REGISTER_BUTTON:
            return True
    return False


class ClassSelect(discord.ui.Select):
    def to_component_dict(self) -> dict:
        # Discord rejects a disabled field inside a modal, even when it is false.
        payload = super().to_component_dict()
        if payload.get("disabled") is False:
            del payload["disabled"]
        return payload


class NameInput(discord.ui.TextInput):
    def to_component_dict(self) -> dict:
        # The visible label lives on the Label wrapper. A null label is not valid.
        payload = super().to_component_dict()
        payload.pop("label", None)
        return payload


class RegisterModal(discord.ui.Modal, title="Регистрация в Lucky Clover"):
    class_pick = discord.ui.Label(
        text="Выбери класс",
        component=ClassSelect(
            custom_id="lc:class",
            placeholder="Маг",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=label, value=value, description=value)
                for value, label in CLASSES
            ],
        ),
    )
    spec_pick = discord.ui.Label(
        text="Основная роль в группе",
        component=discord.ui.RadioGroup(
            custom_id="lc:spec",
            options=[
                discord.RadioGroupOption(label="Танк", value="Tank", description="Tank"),
                discord.RadioGroupOption(label="Хил", value="Heal", description="Heal"),
                discord.RadioGroupOption(label="ДД", value="DPS", description="DPS"),
            ],
        ),
    )
    name_pick = discord.ui.Label(
        text="Имя персонажа",
        description="Имя и фамилия, как в игре",
        component=NameInput(
            custom_id="lc:name",
            placeholder="Например, Arthas",
            min_length=2,
            max_length=32,
            required=True,
        ),
    )

    def __init__(self) -> None:
        # Dismissed forms must leave memory. The id is random so two open forms do not collide.
        super().__init__(timeout=600.0)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != GUILD_ID or interaction.guild is None:
            await reply(interaction, "Анкета работает только на сервере гильдии.")
            return
        member = interaction.user
        if not isinstance(member, discord.Member):
            await reply(interaction, "Анкета работает только на сервере гильдии.")
            return

        class_values = self.class_pick.component.values
        spec_value = self.spec_pick.component.value
        raw_name = self.name_pick.component.value or ""
        class_name = class_values[0] if class_values else ""
        if class_name not in CLASS_NAMES or spec_value not in SPEC_ROLES:
            await reply(interaction, "Анкета заполнена неверно. Открой её ещё раз.")
            return
        nick = clean_nick(raw_name)
        if nick is None:
            await reply(
                interaction,
                "Имя персонажа: от 2 до 32 символов, только буквы, пробел, дефис и апостроф. "
                "Например, Arthas или Arthas Menethil.",
            )
            return

        guild = interaction.guild
        missing: list[str] = []
        resolved: dict[str, discord.Role] = {}
        for name in (class_name, spec_value, INITIATE):
            role = find_role(guild, name)
            if role is None:
                missing.append(name)
                print(f"missing role: {name}", flush=True)
            else:
                resolved[name] = role
        if missing:
            shown = ", ".join(f"`{name}`" for name in missing)
            await reply(interaction, f"На сервере нет ролей: {shown}. Напиши офицеру.")
            return

        class_role = resolved[class_name]
        spec_role = resolved[spec_value]
        initiate = resolved[INITIATE]
        me = guild.me
        if me is None:
            bot_user = interaction.client.user
            if bot_user is None:
                await reply(interaction, "Не получилось завершить регистрацию. Попробуй ещё раз.")
                return
            try:
                me = await guild.fetch_member(bot_user.id)
            except discord.HTTPException as exc:
                print(f"bot member lookup failed: {exc}", flush=True)
                await reply(interaction, "Не получилось завершить регистрацию. Попробуй ещё раз.")
                return
        too_high = [role for role in (class_role, spec_role, initiate) if role >= me.top_role]
        if too_high:
            names = ", ".join(role.name for role in too_high)
            print(f"role above bot: {names}", flush=True)
            shown = ", ".join(f"`{role.name}`" for role in too_high)
            await reply(
                interaction,
                f"Роли {shown} выше роли бота или на одном уровне с ней. "
                "Подними роль бота в списке ролей.",
            )
            return

        roles = next_roles(member, [class_role, spec_role, initiate])
        try:
            nick_set = await apply_member(member, roles, nick, member.id != guild.owner_id)
        except discord.Forbidden:
            print(f"forbidden user={member.id}", flush=True)
            await reply(
                interaction,
                "Бот не смог выдать роли. Проверь права Manage Roles и Manage Nicknames "
                "и подними роль бота выше выдаваемых.",
            )
            return
        except discord.HTTPException as exc:
            print(f"edit failed user={member.id} status={exc.status} {exc}", flush=True)
            await reply(interaction, "Не получилось завершить регистрацию. Попробуй ещё раз.")
            return

        print(
            f"registered user={member.id} nick={nick!r} class={class_role.name} "
            f"spec={spec_role.name} nick_set={nick_set}",
            flush=True,
        )
        if member.id == guild.owner_id:
            nick_line = f"Ник владельца сервера Discord не меняется. Поставь его вручную: {nick}"
        elif not nick_set:
            nick_line = f"Ник не сменился. Поставь его вручную: {nick}"
        else:
            nick_line = f"Ник: **{nick}**."
        await reply(
            interaction,
            f"Доступ открыт.\n{nick_line}\nРоли: {class_role.name}, {spec_role.name}, {INITIATE}.",
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        print(f"modal error: {error!r}", flush=True)
        traceback.print_exc()
        await reply(interaction, "Не получилось завершить регистрацию. Попробуй ещё раз.")


async def apply_member(
    member: discord.Member,
    roles: list[discord.Role],
    nick: str,
    set_nick: bool,
) -> bool:
    """Set roles in one request. Returns whether the nickname was changed."""
    if not set_nick:
        await member.edit(roles=roles, reason=REASON)
        return False
    try:
        await member.edit(nick=nick, roles=roles, reason=REASON)
        return True
    except discord.Forbidden:
        await member.edit(roles=roles, reason=REASON)
        return False
    except discord.HTTPException as exc:
        if exc.status != 400:
            raise
        await member.edit(roles=roles, reason=REASON)
        return False


class RegisterView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Зарегистрироваться",
        style=discord.ButtonStyle.success,
        custom_id=REGISTER_BUTTON,
    )
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild_id != GUILD_ID:
            await reply(interaction, "Эта анкета для другого сервера.")
            return
        await interaction.response.send_modal(RegisterModal())


async def _put(channel: discord.abc.GuildChannel, target: discord.abc.Snowflake, **perms: bool) -> None:
    try:
        await channel.set_permissions(target, reason=REASON, **perms)
    except discord.HTTPException:
        basic = {
            key: perms[key]
            for key in ("view_channel", "send_messages", "read_message_history", "add_reactions")
            if key in perms
        }
        if not basic or basic == perms:
            raise
        await channel.set_permissions(target, reason=REASON, **basic)


async def lock_channels(guild: discord.Guild, bot_id: int) -> str:
    reg = guild.get_channel(REG_CHANNEL_ID)
    if reg is None:
        try:
            reg = await guild.fetch_channel(REG_CHANNEL_ID)
        except discord.HTTPException:
            reg = None
    if not isinstance(reg, discord.TextChannel):
        return "REG_CHANNEL_ID не указывает на текстовый канал этого сервера."

    initiate = find_role(guild, INITIATE)
    if initiate is None:
        print("missing role: Initiate", flush=True)
        return "На сервере нет роли Initiate."

    me = guild.me
    if me is None:
        try:
            me = await guild.fetch_member(bot_id)
        except discord.HTTPException as exc:
            print(f"bot member lookup failed: {exc}", flush=True)
            return "Не вижу роль бота на сервере. Проверь, что бот зашёл в гильдию."
    everyone = guild.default_role
    bot_role = me.top_role
    reg_category_id = reg.category_id
    updated = 0
    failed: list[str] = []

    for channel in guild.channels:
        try:
            if channel.id == reg.id:
                await _put(
                    channel,
                    everyone,
                    view_channel=True,
                    read_message_history=True,
                    send_messages=False,
                    add_reactions=False,
                    attach_files=False,
                    embed_links=False,
                    create_public_threads=False,
                    create_private_threads=False,
                    send_messages_in_threads=False,
                )
                await _put(channel, initiate, view_channel=False)
            elif reg_category_id is not None and channel.id == reg_category_id:
                await _put(channel, everyone, view_channel=True)
                await _put(channel, initiate, view_channel=True)
            else:
                await _put(channel, everyone, view_channel=False)
                await _put(channel, initiate, view_channel=True)
            if bot_role.id != everyone.id:
                await _put(channel, bot_role, view_channel=True)
            updated += 1
        except discord.HTTPException as exc:
            failed.append(channel.name)
            print(f"lock failed channel={channel.id} {exc}", flush=True)

    text = f"Готово. Обновлено каналов: {updated}."
    if failed:
        shown = ", ".join(failed[:8])
        extra = "…" if len(failed) > 8 else ""
        text += f" Не удалось: {shown}{extra}."
    return text


class LockConfirm(discord.ui.View):
    def __init__(self, author_id: int) -> None:
        super().__init__(timeout=180)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await reply(interaction, "Подтверждает тот, кто вызвал команду.")
            return False
        if not is_admin(interaction):
            await reply(interaction, "Команда только для администратора.")
            return False
        return True

    @discord.ui.button(label="Да, закрыть каналы", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        guild = interaction.guild
        bot_user = interaction.client.user
        if guild is None or bot_user is None:
            await reply(interaction, "Команда работает только на сервере гильдии.")
            return
        await interaction.response.edit_message(content="Закрываю каналы…", view=None)
        try:
            result = await lock_channels(guild, bot_user.id)
        except Exception as exc:
            print(f"lock failed: {exc!r}", flush=True)
            traceback.print_exc()
            result = "Не получилось закрыть каналы. Подробности в логе хостинга."
        await interaction.edit_original_response(content=result)

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.edit_message(content="Отменено. Права каналов не менялись.", view=None)


LOCK_WARNING = (
    "Закрою каналы для @everyone.\n"
    "Новый человек увидит только регистрацию и не сможет в ней писать. "
    "Роль Initiate откроет остальные каналы и скроет регистрацию.\n\n"
    "Сначала выдай Initiate всем, кто уже должен видеть сервер. "
    "Без Initiate или права администратора человек останется только на регистрации.\n"
    "У кого есть Initiate, канал регистрации тоже скроется, даже у офицера. "
    "Администратор по-прежнему видит всё.\n"
    "Команда откроет Initiate все каналы, кроме регистрации. "
    "Если есть штабные каналы, после этого сними с них просмотр роли Initiate.\n\n"
    "Продолжить?"
)


class LuckyClover(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(
            intents=intents,
            chunk_guilds_at_startup=False,
            member_cache_flags=discord.MemberCacheFlags.none(),
            max_messages=None,
        )
        self.tree = app_commands.CommandTree(self)
        self._announced = False

    async def setup_hook(self) -> None:
        self.add_view(RegisterView())
        try:
            synced = await self.tree.sync(guild=GUILD)
            print(f"synced {len(synced)} commands", flush=True)
        except discord.HTTPException as exc:
            print(f"command sync failed: {exc}", flush=True)

    async def on_ready(self) -> None:
        if self._announced:
            return
        self._announced = True
        user = self.user
        name = user.name if user else "bot"
        print(f"logged in as {name} guild={GUILD_ID}", flush=True)


client = LuckyClover()


@client.tree.command(
    name="reg-panel",
    description="Опубликовать анкету в этом канале",
    guild=GUILD,
)
@app_commands.default_permissions(administrator=True)
async def reg_panel(interaction: discord.Interaction) -> None:
    if not is_admin(interaction):
        await reply(interaction, "Команда только для администратора.")
        return
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel) or interaction.guild_id != GUILD_ID:
        await reply(interaction, "Открой команду в текстовом канале сервера.")
        return

    await interaction.response.defer(ephemeral=True)
    existing: discord.Message | None = None
    try:
        async for message in channel.history(limit=100):
            author = interaction.client.user
            if author is not None and message.author.id == author.id and has_register_button(message):
                existing = message
                break
    except discord.HTTPException as exc:
        print(f"history failed: {exc}", flush=True)

    embed = panel_embed()
    view = RegisterView()
    if existing is None:
        message = await channel.send(embed=embed, view=view, allowed_mentions=NO_MENTIONS)
        status = "Анкета опубликована в этом канале."
    else:
        message = await existing.edit(embed=embed, view=view, allowed_mentions=NO_MENTIONS)
        status = "Анкета в этом канале обновлена."

    if not message.pinned:
        try:
            await message.pin(reason=REASON)
        except discord.HTTPException as exc:
            print(f"pin failed: {exc}", flush=True)
            status += " Закрепить не удалось: нужно право Manage Messages."
    if channel.id != REG_CHANNEL_ID:
        status += " Это не канал из REG_CHANNEL_ID: /reg-lock откроет людям другой канал."
    await interaction.followup.send(status, ephemeral=True)


@client.tree.command(
    name="reg-lock",
    description="Закрыть каналы для всех, кроме регистрации",
    guild=GUILD,
)
@app_commands.default_permissions(administrator=True)
async def reg_lock(interaction: discord.Interaction) -> None:
    if not is_admin(interaction):
        await reply(interaction, "Команда только для администратора.")
        return
    guild = interaction.guild
    if guild is None or guild.id != GUILD_ID:
        await reply(interaction, "Команда работает только на сервере гильдии.")
        return
    reg = guild.get_channel(REG_CHANNEL_ID)
    if reg is None:
        try:
            reg = await guild.fetch_channel(REG_CHANNEL_ID)
        except discord.HTTPException:
            reg = None
    if not isinstance(reg, discord.TextChannel):
        await reply(interaction, "REG_CHANNEL_ID не указывает на текстовый канал этого сервера.")
        return
    if find_role(guild, INITIATE) is None:
        print("missing role: Initiate", flush=True)
        await reply(interaction, "На сервере нет роли Initiate.")
        return
    await interaction.response.send_message(
        LOCK_WARNING,
        view=LockConfirm(interaction.user.id),
        ephemeral=True,
        allowed_mentions=NO_MENTIONS,
    )


def main() -> None:
    client.run(TOKEN)


if __name__ == "__main__":
    main()
