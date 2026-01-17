import asyncio
import base64
import aiohttp
from typing import Any, Optional
from discord import Embed, app_commands
from redbot.core import commands, checks, Config
from red_commons.logging import getLogger
from redbot.core.utils.chat_formatting import pagify
from redbot.core.utils import menus
import discord
from redbot.core.utils.views import ConfirmView

log = getLogger("red.wizard-cogs.gameserverstatus")


# Класс для ввода данных в модальном окне Discord
class Input(discord.ui.Modal, title='Введите данные сервера'):
    name = discord.ui.TextInput(label='Название', placeholder='Название сервера (можете выбрать любое)', required=True)
    url = discord.ui.TextInput(label='Watchdog URL',
                               placeholder='URL сервера Watchdog (https://ss14.io/watchdog http://localhost:5000)',
                               required=True)
    key = discord.ui.TextInput(label='ID сервера',
                               placeholder='ID сервера (ID экземпляра сервера)',
                               required=True)
    token = discord.ui.TextInput(label='API Токен',
                                 placeholder='Токен сервера (значение ApiToken)',
                                 required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("Обработка...", ephemeral=True)
        self.stop()


# Кнопка для вызова модального окна
class Button(discord.ui.View):
    def __init__(self, member):
        self.member = member
        super().__init__()
        self.modal = None

    @discord.ui.button(label='Добавить', style=discord.ButtonStyle.green)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.member != interaction.user:
            return await interaction.response.send_message("Вы не можете использовать эту кнопку.", ephemeral=True)

        self.modal = Input()
        await interaction.response.send_modal(self.modal)
        await self.modal.wait()
        self.stop()

ACTION_TIMEOUT = 5

async def doaction(session: aiohttp.ClientSession, server, action: str) -> tuple[int, str]:
    async def load() -> tuple[int, str]:
        async with session.post(server["address"] + f"/instances/{server['key']}/{action}",
                                auth=aiohttp.BasicAuth(server['key'], server['token'])) as resp:
            return resp.status, await resp.text()

    return await asyncio.wait_for(load(), timeout=ACTION_TIMEOUT)

class poweractions(commands.Cog):
    def __init__(self, bot, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = Config.get_conf(self, identifier=275978)

        default_guild = {
            "servers": {},
        }

        self.config.register_guild(**default_guild)

        self.bot = bot

    @commands.hybrid_group()
    @checks.admin()
    async def poweractionscfg(self, ctx: commands.Context) -> None:
        """
        Команды для настройки серверов, чтобы можно было управлять действиями для power actions.
        """
        pass

    @poweractionscfg.command()
    async def add(self, ctx: commands.Context) -> None:
        """
        Добавляет сервер.
        """
        view = Button(member=ctx.author)

        await ctx.send("Чтобы добавить сервер, нажмите эту кнопку.", view=view)
        await view.wait()
        if view.modal is None:
            return
        if not view.modal.name.value:
            return

        async with self.config.guild(ctx.guild).servers() as cur_servers:
            if view.modal.name.value in cur_servers:
                await ctx.send("Сервер с таким названием уже существует.")
                return

            if not view.modal.url.value.startswith("http://") and not view.modal.url.value.startswith("https://"):
                await ctx.send("URL должен начинаться с http:// или https://")
                return

            # Убираем завершающий слеш в конце URL
            if view.modal.url.value.endswith("/"):
                await ctx.send("Удалите завершающий слеш в конце URL.")

            if view.modal.url.value.endswith(f"/instances/{view.modal.key.value}/restart"):
                await ctx.send("Не нужно указывать последнюю часть URL, только базовый URL до watchdog (Пример: "
                               "https://ss14.io/watchdog, http://localhost:5000)")
                return

            cur_servers[view.modal.name.value] = {
                "address": view.modal.url.value,
                "key": view.modal.key.value,
                "token": view.modal.token.value
            }

        await ctx.send("Сервер успешно добавлен.")

    @poweractionscfg.command()
    async def remove(self, ctx: commands.Context, name: str) -> None:
        """
        Удаляет сервер.

        `<name>`: Название сервера для удаления.
        """
        async with self.config.guild(ctx.guild).servers() as cur_servers:
            if name not in cur_servers:
                await ctx.send("Этого сервера не существует.")
                return

            del cur_servers[name]

        await ctx.tick()

    @poweractionscfg.command()
    async def list(self, ctx: commands.Context) -> None:
        """
        Получить список серверов.
        """
        servers = await self.config.guild(ctx.guild).servers()

        if len(servers) == 0:
            await ctx.send("В настоящее время нет настроенных серверов!")
            return

        content = "\n".join(map(lambda s: f"{s[0]}: `{s[1]['address']}`", servers.items()))

        pages = list(pagify(content, page_length=1024))
        embed_pages = []
        for idx, page in enumerate(pages, start=1):
            embed = discord.Embed(
                title="Список серверов",
                description=page,
                colour=await ctx.embed_colour(),
            )
            embed.set_footer(text="Страница {num}/{total}".format(num=idx, total=len(pages)))
            embed_pages.append(embed)
        await menus.menu(ctx, embed_pages, menus.DEFAULT_CONTROLS)

    @checks.admin()
    @commands.hybrid_command()
    async def restartserver(self, ctx: commands.Context, server: Optional[str]) -> None:
        """
        Перезапускает сервер.

        `<server>`: Название сервера для перезапуска.
        """
        if not server:
            await self.list(ctx)
            return

        async with ctx.typing():
            foundServer = await self.get_server_from_arg(ctx, server)
            if foundServer is None:
                return
            
            servername, server = foundServer

            async with aiohttp.ClientSession() as session:
                try:
                    status, response = await doaction(session, server, "restart")
                    if status != 200:
                        await ctx.send(f"Не удалось перезапустить сервер. Неверный код статуса: {status}")
                        log.debug(f"Не удалось перезапустить {servername}. Неверный код статуса: {status} Ответ: {response}")
                        return

                except asyncio.TimeoutError:
                    await ctx.send("Сервер не ответил вовремя.")
                    return

                except Exception:
                    await ctx.send(
                        f"Произошла неизвестная ошибка при попытке перезапустить этот сервер. Подробности в консоли...")
                    log.exception(
                        f"Произошла ошибка при попытке перезапустить сервер {servername}.")
                    return

            await ctx.send("Сервер успешно перезапущен.")

    @checks.admin()
    @commands.hybrid_command()
    async def updateserver(self, ctx: commands.Context, server: Optional[str]) -> None:
        """
        Отправляет запрос на обновление серверу.

        `<server>`: Название сервера для обновления.
        """
        if not server:
            await self.list(ctx)
            return

        async with ctx.typing():
            foundServer = await self.get_server_from_arg(ctx, server)
            if foundServer is None:
                return

            servername, server = foundServer

            async with aiohttp.ClientSession() as session:
                try:
                    status, response = await doaction(session, server, "update")
                    if status != 200:
                        await ctx.send(f"Не удалось отправить запрос на обновление сервера. Неверный код статуса: {status}")
                        log.debug(f"Не удалось обновить {servername}. Неверный код статуса: {status} Ответ: {response}")
                        return

                except asyncio.TimeoutError:
                    await ctx.send("Сервер не ответил вовремя.")
                    return

                except Exception:
                    await ctx.send(
                        f"Произошла неизвестная ошибка при попытке запросить обновление этого сервера. Подробности в консоли...")
                    log.exception(
                        f"Произошла ошибка при попытке обновить сервер {servername}.")
                    return

            await ctx.send("Серверу успешно отправлена команда на обновление.")

    @checks.admin()
    @commands.hybrid_command()
    async def stopserver(self, ctx: commands.Context, server: Optional[str]) -> None:
        """
        Останавливает сервер. Сервер дождётся окончания раунда, но автоматически не перезапустится.

        `<server>`: Название сервера для остановки.
        """
        if not server:
            await self.list(ctx)
            return
    
        async with ctx.typing():
            foundServer = await self.get_server_from_arg(ctx, server)
            if foundServer is None:
                return
            
            servername, server = foundServer

            async with aiohttp.ClientSession() as session:
                try:
                    status, response = await doaction(session, server, "stop")
                    if status != 200:
                        await ctx.send(f"Не удалось остановить сервер. Неверный код статуса: {status}")
                        log.debug(f"Не удалось остановить {servername}. Неверный код статуса: {status} Ответ: {response}")
                        return

                except asyncio.TimeoutError:
                    await ctx.send("Сервер не ответил вовремя.")
                    return

                except Exception:
                    await ctx.send(
                        f"Произошла неизвестная ошибка при попытке остановить этот сервер. Подробности в консоли...")
                    log.exception(
                        f"Произошла ошибка при попытке остановить сервер {servername}.")
                    return

            await ctx.send("Сервер успешно остановлен.")

    async def get_server_from_arg(self, ctx: commands.Context, server) -> Optional[Any]:
        selectedserver = await self.config.guild(ctx.guild).servers()

        if server not in selectedserver:
            await ctx.send("Такого сервера не существует.")
            return None

        return (server, selectedserver[server])

    @checks.admin()
    @commands.hybrid_command()
    async def restartnetwork(self, ctx: commands.Context) -> None:
        """
        Пытается перезапустить все серверы, настроенные у этого бота.
        """
        view = ConfirmView(ctx.author, disable_buttons=True, timeout=30)
        view.message = await ctx.send(":warning: Вы собираетесь перезапустить все серверы, настроенные у этого экземпляра бота. "
                                      "Вы уверены, что хотите это сделать?", view=view)
        await view.wait()
        if not view.result:
            await ctx.send("Отменено. Действий не произведено.")
            return
        else:
            await ctx.send("Перезапуск всех серверов...")
            async with ctx.typing():
                network_data = await self.config.guild(ctx.guild).servers()

                embed = Embed(title="Сетевой перезапуск", description="Результаты перезапусков",
                              color=await ctx.embed_colour())

                async with aiohttp.ClientSession() as session:
                    for server_name, server_details in network_data.items():
                        try:
                            status, response = await doaction(session, server_details, "restart")
                            if status != 200:
                                embed.add_field(name=server_name, value=f":x: Неверный код статуса: {status}",
                                                inline=False)
                                log.debug(f"(Сетевой перезапуск) Не удалось перезапустить {server_details[0]}. "
                                          f"Неверный код статуса: {status} Ответ: {response}")
                            else:
                                embed.add_field(name=server_name, value=":white_check_mark: Успешно", inline=False)

                        except asyncio.TimeoutError:
                            embed.add_field(name=server_name, value=":x: Превышено время ожидания", inline=False)

                        except Exception:
                            embed.add_field(name=server_name, value=":x: Неизвестная ошибка. Подробности в консоли",
                                            inline=False)
                            log.exception(
                                f"(Сетевой перезапуск) Произошла ошибка при попытке перезапустить сервер {server_name}.")

                await ctx.send("Готово", embed=embed)
                