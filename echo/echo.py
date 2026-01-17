import discord, re
from discord.channel import TextChannel
from discord.message import Message
from discord.utils import escape_markdown, escape_mentions
from redbot.core import commands, bot, Config, checks

class Echo(commands.Cog):
    def __init__(self, bot: bot.Red) -> None:
        self.bot = bot

    @commands.group()
    @checks.admin()
    async def adminmsg(self, ctx: commands.Context) -> None:
        """
        Команды для управления и создания административных сообщений.
        """
        pass

    @adminmsg.command()
    async def create(self, ctx: commands.Context, chan: TextChannel) -> None:
        """
        Создать административное сообщение в указанном канале.
        Содержимое сообщения — это всё, кроме первой строки сообщения, вызвавшего команду, и копируется дословно.
        """
        msg = "\n".join(ctx.message.content.split("\n")[1:])
        if not msg:
            await ctx.reply("Сообщение пустое! Поместите его на новую строку!")
            return

        try:
            await chan.send(msg)
        except discord.Forbidden:
            await ctx.reply("У меня нет разрешения отправлять сообщения туда!")
            return

        await ctx.tick()

    @adminmsg.command()
    async def edit(self, ctx: commands.Context, editMessage: Message) -> None:
        """
        Редактирует содержимое сообщения, отправленного ботом.
        Содержимое сообщения — это всё, кроме первой строки сообщения, вызвавшего команду, и копируется дословно.
        """
        msg = "\n".join(ctx.message.content.split("\n")[1:])
        if not msg:
            await ctx.reply("Сообщение пустое! Поместите его на новую строку!")
            return

        if editMessage.author != self.bot.user:
            await ctx.reply("Я не отправлял это сообщение!")
            return

        await editMessage.edit(content=msg)
        await ctx.tick()

    @adminmsg.command()
    async def raw(self, ctx: commands.Context, message: Message) -> None:
        """
        Возвращает исходное содержимое сообщения, экранируя эмодзи, упоминания и каналы.
        Полезно для редактирования существующих сообщений.
        """

        if message.author != self.bot.user:
            await ctx.reply("Я не отправлял это сообщение!")
            return

        # Регулярное выражение для эмодзи.
        re_emoji = re.compile(
            "["
            "\U0001F1E0-\U0001F1FF"
            "\U0001F300-\U0001F5FF"
            "\U0001F600-\U0001F64F"
            "\U0001F680-\U0001F6FF"
            "\U0001F700-\U0001F77F"
            "\U0001F780-\U0001F7FF"
            "\U0001F800-\U0001F8FF"
            "\U0001F900-\U0001F9FF"
            "\U0001FA00-\U0001FA6F"
            "\U0001FA70-\U0001FAFF"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251" 
            "]+", flags=re.UNICODE
        )

        contents = escape_markdown(message.content)\
            .replace("<@!", "<\\@")\
            .replace("<@&", "<\\@&")\
            .replace("<#", "<\\#")\
            .replace("<:", "\\<:")\
            .replace("@here", "\\@here")\
            .replace("@everyone", "\\@everyone")

        for emoji in re_emoji.findall(contents):
            contents = contents.replace(emoji, f"\\{emoji}")

        await ctx.send(contents)
        await ctx.tick()