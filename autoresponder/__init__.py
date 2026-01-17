from .responder import Responder

async def setup(bot):
    await bot.add_cog(Responder(bot))
