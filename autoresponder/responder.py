import re
import discord
import random
from redbot.core import commands, Config
from redbot.core.utils.views import ConfirmView
from redbot.core.utils import menus
from redbot.core.utils.chat_formatting import pagify
from typing import Optional, Dict, List

class AddTriggerModal(discord.ui.Modal, title="Добавить автоответ"):
    trigger = discord.ui.TextInput(
        label="Триггер (регулярное выражение или текст)",
        placeholder=r"например: .*tetris.*",
        required=True,
    )
    response = discord.ui.TextInput(
        label="Ответ",
        placeholder="например: *Nanotrasen Block Game™",
        required=True,
    )
    case_sensitive = discord.ui.TextInput(
        label="Учитывать регистр? (да/нет)",
        placeholder="нет",
        required=False,
        default="нет",
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("Автоответ добавлен!", ephemeral=True)
        self.stop()

class TriggerButtons(discord.ui.View):
    def __init__(self, member: discord.Member):
        super().__init__()
        self.member = member
        self.modal = None

    @discord.ui.button(label="Добавить", style=discord.ButtonStyle.green)
    async def add_trigger(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.member:
            return await interaction.response.send_message("Вы не можете использовать эту кнопку.", ephemeral=True)
        self.modal = AddTriggerModal()
        await interaction.response.send_modal(self.modal)
        await self.modal.wait()
        self.stop()

class RemoveTriggerSelect(discord.ui.Select):
    def __init__(self, triggers: Dict[str, Dict[str, str]]):
        options = [
            discord.SelectOption(label=f"{trigger} → {data['response'][:50]}...", value=trigger)
            for trigger, data in triggers.items()
        ]
        super().__init__(placeholder="Выберите автоответ для удаления:", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"Удаляю автоответ: `{self.values[0]}`", ephemeral=True)
        self.stop()

class RemoveTriggerView(discord.ui.View):
    def __init__(self, triggers: Dict[str, Dict[str, str]]):
        super().__init__()
        self.select = RemoveTriggerSelect(triggers)
        self.add_item(self.select)

class Responder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {"triggers": {}}
        self.config.register_guild(**default_guild)

    @commands.hybrid_group()
    @commands.admin()
    async def autoresponder(self, ctx: commands.Context):
        """Управление автоответами."""
        pass

    @autoresponder.command(name="add")
    async def add_trigger(self, ctx: commands.Context):
        """Добавить новый автоответ."""
        view = TriggerButtons(ctx.author)
        await ctx.send("Нажмите кнопку, чтобы добавить автоответ.", view=view)
        await view.wait()
        if view.modal:
            trigger = view.modal.trigger.value
            response = view.modal.response.value
            case_sensitive = view.modal.case_sensitive.value.lower() == "да"
            flags = 0 if case_sensitive else re.IGNORECASE
            async with self.config.guild(ctx.guild).triggers() as triggers:
                triggers[trigger] = {"response": response, "flags": flags}
            await ctx.send(f"Триггер `{trigger}` добавлен!")

    @autoresponder.command(name="remove")
    async def remove_trigger(self, ctx: commands.Context):
        """Удалить автоответ."""
        triggers = await self.config.guild(ctx.guild).triggers()
        if not triggers:
            return await ctx.send("Нет добавленных автоответов.")

        view = RemoveTriggerView(triggers)
        await ctx.send("Выберите автоответ для удаления:", view=view)
        await view.wait()

        if view.select.values:
            trigger = view.select.values[0]
            async with self.config.guild(ctx.guild).triggers() as triggers:
                del triggers[trigger]
            await ctx.send(f"Автоответ `{trigger}` удалён!")

    @autoresponder.command(name="list")
    async def list_triggers(self, ctx: commands.Context):
        """Показать все автоответы (включая встроенные)."""
        dynamic_triggers = await self.config.guild(ctx.guild).triggers()
        dynamic_content = "\n".join(f"`{t}` → {d['response']}" for t, d in dynamic_triggers.items())

        static_triggers = {
            r".*tetris.*": "*Nanotrasen Block Game™",
            r"\S\s+(?:when|whence)[\s*?.!)]*$": "When You Code It. / Никогда.",
            r"^\s*(based|gebaseerd|basé|basato|basado|basiert|βασισμένο|βασισμενο|ベース)[\s*?.!)]*$": "Основано на чём? / Не основано. (и другие языки)",
        }
        static_content = "\n".join(f"`{t}` → {r}" for t, r in static_triggers.items())

        content = "**Динамические автоответы:**\n"
        content += dynamic_content if dynamic_content else "Нет динамических автоответов.\n"
        content += "\n**Встроенные автоответы:**\n"
        content += static_content

        pages = list(pagify(content, page_length=1024))
        embed_pages = []
        for idx, page in enumerate(pages, start=1):
            embed = discord.Embed(
                title="Все автоответы",
                description=page,
                color=await ctx.embed_colour(),
            )
            embed.set_footer(text=f"Страница {idx}/{len(pages)}")
            embed_pages.append(embed)
        await menus.menu(ctx, embed_pages, menus.DEFAULT_CONTROLS)

    @commands.command()
    async def regexhelp(self, ctx: commands.Context):
        """Помощь по регулярным выражениям."""
        regex_help = """
**Регулярные выражения (regex) — краткая справка**

Регулярные выражения используются для поиска и сопоставления текста по шаблону.

### Основные символы и конструкции:
- `.` — любой символ, кроме новой строки.
- `*` — ноль или более повторений предыдущего символа.
- `+` — одно или более повторений предыдущего символа.
- `?` — ноль или одно повторение предыдущего символа.
- `\d` — любая цифра.
- `\w` — любая буква, цифра или подчёркивание.
- `\s` — любой пробельный символ (пробел, табуляция, новая строка).
- `[abc]` — любой из символов `a`, `b` или `c`.
- `(a|b)` — либо `a`, либо `b`.
- `^` — начало строки.
- `$` — конец строки.
- `\b` — граница слова.

### Примеры:
- `.*tetris.*` — любая строка, содержащая слово `tetris`.
- `^\s*when\s*$` — строка, содержащая только слово `when` (с возможными пробелами).
- `\d{3}` — ровно три цифры подряд.
- `[A-Za-z]+` — одна или более латинских букв.

**Дополнительно:**
- Для тестирования регулярных выражений можно использовать онлайн-сервисы, например, [regex101.com](https://regex101.com/).
"""
        await ctx.send(regex_help)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or await self.bot.is_automod_immune(message):
            return
        guild = message.guild
        if not guild:
            return
        triggers = await self.config.guild(guild).triggers()
        for trigger, data in triggers.items():
            if re.search(trigger, message.content, data["flags"]):
                await message.channel.send(data["response"])
                break

    @commands.Cog.listener("on_message_without_command")
    async def on_message_without_command(self, message: discord.Message):
        if message.author.bot or await self.bot.is_automod_immune(message):
            return
        channel = message.channel
        content = message.content

        # Tetris
        if re.search(r".*tetris.*", content, re.IGNORECASE):
            await channel.send("*Nanotrasen Block Game™")

        # WYCI
        if re.search(r"\S\s+(?:when|whence)[\s*?.!)]*$", content, re.IGNORECASE):
            if random.random() > 0.005:
                await channel.send("When You Code It.")
            else:
                await channel.send("Никогда.")

        # Based
        match = re.search(
            r"^\s*(based|gebaseerd|basé|basato|basado|basiert|βασισμένο|βασισμενο|ベース)[\s*?.!)]*$",
            content,
            re.IGNORECASE,
        )
        if match:
            based_responses = {
                "based": ("Основано на чём?", "Не основано."),
                "gebaseerd": ("Gebaseerd op wat?", "Niet Gebaseerd."),
                "basé": ("Sur quoi?", "Pas basé."),
                "basato": ("Basato su cosa?", "Non basato."),
                "basado": ("¿Basado en qué?", "No basado."),
                "basiert": ("Worauf?", "Nicht basiert."),
                "βασισμένο": ("Βασισμένο σε τι;", "Αβάσιμο."),
                "βασισμενο": ("Βασισμένο σε τι;", "Αβάσιμο."),
                "ベース": ("何に基づいてですか", "ベースではない"),
            }
            key = match.group(1).lower()
            based, unbased = based_responses.get(key, ("Основано на чём?", "Не основано."))
            if random.random() > 0.005:
                await channel.send(based)
            else:
                await channel.send(unbased)