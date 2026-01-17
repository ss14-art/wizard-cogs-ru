import aiohttp
import dateutil.parser
import logging

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, TypeVar, Callable
from urllib.parse import urlparse, urlunparse

import discord
from discord import TextChannel
from discord.ext import tasks

from redbot.core import app_commands, commands, bot, Config, checks
from redbot.core.utils import menus
from redbot.core.utils.chat_formatting import pagify, humanize_timedelta

log = logging.getLogger("red.wizard-cogs.gameserverstatus")

SS14_RUN_LEVEL_STATUS = {
    0: "В лобби",
    1: "В игре",
    2: "Завершается",
}


class StatusFetchError(Exception):
    pass


class SS14ServerStatus(discord.ui.LayoutView):
    def __init__(
        self,
        *,
        name: str,
        player_count: str,
        status: str,
        preset: str,
        round_id: str,
        color: discord.Color,
    ):
        super().__init__()

        self.container = discord.ui.Container(
            discord.ui.TextDisplay(content=f"**{name}**"),
            discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            discord.ui.TextDisplay(
                content=f"**Игроки:** {player_count}\n**Статус:** {status}\n**Пресет:** {preset}"
            ),
            accent_color=color,
        )
        self.footer_text = discord.ui.TextDisplay(content=f"-# ID раунда: {round_id}")

        self.add_item(self.container)
        self.add_item(self.footer_text)


class GameServerStatus(commands.Cog):
    def __init__(self, bot: bot.Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=5645456348)
        self.session = aiohttp.ClientSession(
            headers={
                "User-Agent": "Py Aiohttp - Wizard-cogs/GameServerStatus (+https://github.com/space-wizards/wizard-cogs)"
            }
        )

        default_guild: Dict[str, Any] = {"servers": {}, "watches": [], "slashcommandvisible": True}
        self.config.register_guild(**default_guild)

        self.printer.start()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        # Удаляем наблюдателей при удалении гильдии
        await self.config.guild(guild).watches.clear()

    async def cog_unload(self) -> None:
        await self.session.close()
        self.printer.cancel()

    @commands.command()
    @commands.guild_only()
    async def status(
        self,
        ctx: commands.Context,
        server: Optional[str],
        legacy: Optional[bool] = False,
    ) -> None:
        """Показывает статус игрового сервера.

        Оставьте название сервера пустым, чтобы получить список всех серверов.
        Установите `legacy` в `True`, чтобы отобразить статус в виде старого Discord-embed.
        """
        if not server:
            await self.show_server_list(ctx)
            return

        async with ctx.typing():
            server = server.lower()
            cfg = await self.config.guild(ctx.guild).servers()
            cfg_lower = {key.lower(): value for (key, value) in cfg.items()}

            if server not in cfg_lower:
                await ctx.send("Такого сервера не существует!")
                return

            data = cfg_lower[server]
            try:
                fetched_data = await self.get_ss14_server_status(data)
            except StatusFetchError:
                return await ctx.send("Произошла ошибка при получении информации о сервере.")

            if legacy is True:
                return await ctx.send(
                    embed=legacy_embed(
                        **fetched_data, color=await self.bot.get_embed_color(ctx)
                    )
                )
            else:
                component_view = SS14ServerStatus(
                    **fetched_data,
                    color=await self.bot.get_embed_color(ctx),
                )
                return await ctx.send(view=component_view)

    @app_commands.command(name="status")
    @app_commands.guild_only()
    @app_commands.guild_install()
    @app_commands.rename(server_name="server")
    async def slash_status(
        self, interaction: discord.Interaction, server_name: str, legacy: bool = False
    ) -> None:
        """Показывает статус игрового сервера.

        Parameters
        -----------
        server: str
            Сервер для запроса.
        legacy: bool
            Режим совместимости для старых клиентов Discord
        """
        server_name = server_name.lower()
        game_servers: dict = await self.config.guild(interaction.guild).servers()
        visible_command = not await self.config.guild(interaction.guild).slashcommandvisible()

        game_server_data = game_servers.get(server_name)
        if game_server_data is None:
            return await interaction.response.send_message(
                "Такого сервера не существует!", ephemeral=True
            )

        await interaction.response.defer(thinking=True, ephemeral=visible_command)
        try:
            fetched_data = await self.get_ss14_server_status(game_server_data)
        except StatusFetchError:
            return await interaction.followup.send(
                "Произошла ошибка при получении информации о сервере."
            )

        if legacy is True:
            return await interaction.followup.send(
                ephemeral=visible_command,
                embed=legacy_embed(
                    **fetched_data,
                    color=await self.bot.get_embed_color(interaction.channel),
                )
            )
        else:
            return await interaction.followup.send(
                ephemeral=visible_command,
                view=SS14ServerStatus(
                    **fetched_data,
                    color=await self.bot.get_embed_color(interaction.channel),
                )
            )

    @slash_status.autocomplete("server_name")
    async def slash_status_server_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        server_names = list(
            (await self.config.guild(interaction.guild).servers()).keys()
        )
        return [
            app_commands.Choice(name=server.capitalize(), value=server)
            for server in server_names
            if current.lower() in server.lower()
        ][:25]

    async def show_server_list(self, ctx: commands.Context) -> None:
        servers = await self.config.guild(ctx.guild).servers()

        if len(servers) == 0:
            await ctx.send("В настоящее время нет настроенных серверов!")
            return

        content = "\n".join(
            map(lambda s: f"{s[0]}: `{s[1]['address']}`", servers.items())
        )

        pages = list(pagify(content, page_length=1024))
        embed_pages = []
        for idx, page in enumerate(pages, start=1):
            embed = discord.Embed(
                title="Список серверов",
                description=page,
                colour=await ctx.embed_colour(),
            )
            embed.set_footer(
                text=f"Страница {idx}/{len(pages)}"
            )
            embed_pages.append(embed)
        await menus.menu(ctx, embed_pages, menus.DEFAULT_CONTROLS)

    async def get_ss14_server_status(self, config: Dict[str, str]) -> Dict[str, str]:
        """Получает и возвращает конечную точку статуса с сервера SS14."""
        cfgurl = config["address"]
        addr = get_ss14_status_url(cfgurl)
        log.debug("SS14 addr is %s", addr)

        try:
            log.debug("Начинаю запрос")
            async with self.session.get(addr + "/status", timeout=10) as resp:
                if resp.status != 200:
                    raise StatusFetchError
                log.debug("Получен ответ.")
                json_data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise StatusFetchError

        count = json_data.get("players", "?")
        count_max = json_data.get("soft_max_players", "?")
        name = json_data.get("name", "?")
        round_id = json_data.get("round_id", "?")
        preset = json_data.get("preset", "?")
        run_level = json_data.get("run_level")
        round_start_time = json_data.get("round_start_time")

        player_count = f"{count}/{count_max}"
        if run_level == 1 and round_start_time is not None:
            start_time = dateutil.parser.isoparse(round_start_time)
            delta = datetime.now(timezone.utc) - start_time
            status = f"{SS14_RUN_LEVEL_STATUS.get(run_level, 'неизвестно')} ({humanize_timedelta(timedelta=delta, maximum_units=2)})"
        else:
            status = SS14_RUN_LEVEL_STATUS.get(run_level, "Неизвестно")

        return {
            "name": name,
            "player_count": player_count,
            "status": status,
            "preset": preset,
            "round_id": round_id,
        }

    @commands.group()
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def statuscfg(self, ctx: commands.Context) -> None:
        """
        Команды для настройки серверов статусов.
        """
        pass

    @statuscfg.group()
    async def addserver(self, ctx: commands.Context) -> None:
        """
        Добавляет сервер статуса.
        """
        pass

    @addserver.command(name="ss14")
    async def addserver_ss14(
        self, ctx: commands.Context, name: str, address: str, longname: Optional[str] = None
    ) -> None:
        """
        Добавляет сервер типа SS14.

        `<name>`: Короткое имя для обращения к этому серверу.
        `<address>`: Адрес `ss14://` или `ss14s://` этого сервера.
        `[longname]`: "Полное название" этого сервера.
        """
        name = name.lower()
        address = address.rstrip("/")

        async with self.config.guild(ctx.guild).servers() as cur_servers:
            if name in cur_servers:
                return await ctx.send("Сервер с таким именем уже существует.")

            cur_servers[name] = {
                "type": "ss14",
                "address": address,
                "name": longname,
            }
        await ctx.tick()

    @statuscfg.command()
    async def removeserver(self, ctx: commands.Context, name: str) -> None:
        """
        Удаляет сервер статуса.

        `<name>`: Название сервера для удаления.
        """
        name = name.lower()
        async with self.config.guild(ctx.guild).servers() as cur_servers:
            if name not in cur_servers:
                await ctx.send("Этого сервера не существовало.")
                return

            del cur_servers[name]

        async with self.config.guild(ctx.guild).watches() as watches:
            watches[:] = [w for w in watches if w["server"] != name]

        await ctx.tick()

    @statuscfg.command()
    async def addwatch(
        self, ctx: commands.Context, name: str, channel: TextChannel
    ) -> None:
        """
        Добавляет сервер в список наблюдения. Бот будет обновлять сообщение со статусом сервера каждую минуту.

        `<name>`: Название сервера для наблюдения.
        `<channel>`: Канал, в который будет отправлено сообщение.
        """
        name = name.lower()
        async with self.config.guild(ctx.guild).watches() as watches:
            servers = await self.config.guild(ctx.guild).servers()

            if name not in servers:
                await ctx.send("Такого сервера не существует!")
                return

            data = servers[name]

            fetched_data = await self.get_ss14_server_status(data)
            component_view = SS14ServerStatus(
                **fetched_data, color=await self.bot.get_embed_color(ctx.channel)
            )

            msg = await channel.send(view=component_view)
            watches.append({"message": msg.id, "server": name, "channel": channel.id})

            await ctx.send("Наблюдение за сервером успешно добавлено.")

    @statuscfg.command()
    async def remwatch(
        self, ctx: commands.Context, name: str, channel: TextChannel
    ) -> None:
        """
        Удаляет сервер из списка наблюдения.

        `<name>`: Название сервера для удаления из наблюдения.
        `<channel>`: Канал, из которого нужно удалить.
        """
        name = name.lower()
        async with self.config.guild(ctx.guild).watches() as watches:
            initial_len = len(watches)
            watches[:] = [w for w in watches if not (w["server"] == name and w["channel"] == channel.id)]
            
            if len(watches) == initial_len:
                await ctx.send("Наблюдение не найдено.")
                return

        await ctx.tick()

    async def remove_watch_message(
        self, guild: discord.Guild, watch_data: Dict[str, Any]
    ) -> None:
        channel = guild.get_channel(watch_data["channel"])
        if channel:
            try:
                message = await channel.fetch_message(watch_data["message"])
                await message.delete()
            except discord.NotFound:
                pass
            except Exception as e:
                log.exception("Ошибка при удалении сообщения наблюдения", exc_info=e)

    @statuscfg.command()
    async def watches(self, ctx: commands.Context) -> None:
        """
        Выводит список активных наблюдений
        """
        watches = await self.config.guild(ctx.guild).watches()

        if len(watches) == 0:
            await ctx.send("В настоящее время нет настроенных наблюдений!")
            return

        content = "\n".join(
            f"<#{w['channel']}> - {w['server']} - [сообщение](https://discord.com/channels/{ctx.guild.id}/{w['channel']}/{w['message']})"
            for w in watches
        )

        pages = list(pagify(content, page_length=1024))
        embed_pages = []
        for idx, page in enumerate(pages, start=1):
            embed = discord.Embed(
                title="Список наблюдений",
                description=page,
                colour=await ctx.embed_colour(),
            )
            embed.set_footer(
                text=f"Страница {idx}/{len(pages)}"
            )
            embed_pages.append(embed)
        await menus.menu(ctx, embed_pages, menus.DEFAULT_CONTROLS)

    @tasks.loop(minutes=1)
    async def printer(self) -> None:
        log.debug("Запуск цикла наблюдателя.")
        try:
            for guild_id, data in (await self.config.all_guilds()).items():
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                for watch in data.get("watches", []):
                    msg_id = watch["message"]
                    ch_id = watch["channel"]
                    server = watch["server"]

                    try:
                        channel = guild.get_channel(ch_id)
                        if not channel:
                            continue
                        msg = await channel.fetch_message(msg_id)
                    except discord.NotFound:
                        async with self.config.guild(guild).watches() as w_config:
                            w_config[:] = [w for w in w_config if w["message"] != msg_id]
                        continue
                    except discord.Forbidden:
                        continue

                    server_data = data.get("servers", {}).get(server)
                    if not server_data:
                        continue

                    try:
                        fetched_data = await self.get_ss14_server_status(server_data)
                    except StatusFetchError:
                        continue

                    view = SS14ServerStatus(
                        **fetched_data, color=await self.bot.get_embed_color(msg)
                    )
                    
                    try:
                        await msg.edit(content="", embed=None, view=view)
                    except discord.HTTPException:
                        pass
                        
        except Exception as e:
            log.exception("Произошла ошибка в цикле printer.", exc_info=e)

    @statuscfg.command()
    async def slashcommandvisible(self, ctx: commands.Context, enabled: bool = None):
        """
        Должны ли слеш-команды быть скрытыми? (Видимы только отправителю.)
        """
        if enabled is None:
            setting = await self.config.guild(ctx.guild).slashcommandvisible()
            if setting:
                await ctx.send("Слеш-команды статуса в настоящее время видны всем в канале, где они запущены.")
            else:
                await ctx.send("Слеш-команды статуса в настоящее время видны только отправителю.")
            return
            
        await self.config.guild(ctx.guild).slashcommandvisible.set(enabled)
        await ctx.tick()

    @printer.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()


def get_ss14_status_url(url: str) -> str:
    if "//" not in url:
        url = "//" + url

    parsed = urlparse(url, "ss14", allow_fragments=False)

    port = parsed.port
    if not port:
        if parsed.scheme == "ss14s":
            port = 443
        else:
            port = 1212

    if parsed.scheme == "ss14s":
        scheme = "https"
    else:
        scheme = "http"

    return urlunparse(
        (
            scheme,
            f"{parsed.hostname}:{port}",
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def legacy_embed(
    *,
    name: str,
    player_count: str,
    status: str,
    preset: str,
    round_id: str,
    color: discord.Color,
) -> discord.Embed:
    embed = discord.Embed(color=color, title=name)
    embed.add_field(name="Игроков онлайн", value=player_count)
    embed.add_field(name="Статус", value=status)
    embed.add_field(name="ID раунда", value=round_id)
    embed.add_field(name="Пресет", value=preset)
    return embed


T = TypeVar("T")


def remove_list_elems(itter_list: List[T], pred: Callable[[T], bool]) -> None:
    itter_list[:] = [item for item in itter_list if not pred(item)]
    
