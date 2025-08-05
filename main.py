import discord
from discord.ext import commands
import os
from datetime import datetime
import json
import asyncio
from discord import ui, Interaction, Embed, ButtonStyle
from alive import keep_alive

keep_alive()

pending_sticky_tasks = {}  # channel_id -> asyncio.Task
STICKY_DELAY_SECONDS = 5   # Tiempo antes de reenviar sticky

STICKY_FILE = "sticky_data.json"

def load_stickies():
    if not os.path.exists(STICKY_FILE):
        return {}
    with open(STICKY_FILE, "r") as f:
        return json.load(f)

def save_stickies(data):
    with open(STICKY_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print("💾 Sticky guardado en archivo.")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

sticky_messages = {}  # {channel_id: discord.Message}
sticky_embeds = {}    # {channel_id: discord.Embed}
sticky_config_data = load_stickies()

async def try_delete_message(channel, message_id):
    try:
        msg = await channel.fetch_message(message_id)
        await msg.delete()
        print(f"🗑️ Mensaje {message_id} borrado del canal {channel.id}")
    except discord.NotFound:
        print(f"⚠️ Mensaje {message_id} no encontrado en canal {channel.id}")
    except discord.Forbidden:
        print(f"❌ Sin permisos para borrar mensaje {message_id} en canal {channel.id}")
    except Exception as e:
        print(f"❌ Error borrando mensaje {message_id} en canal {channel.id}: {e}")

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🌐 Comandos slash sincronizados ({len(synced)})")
    except Exception as e:
        print(f"❌ Error al sincronizar comandos slash: {e}")

    for channel_id_str, config in sticky_config_data.items():
        try:
            channel_id = int(channel_id_str)
            channel = bot.get_channel(channel_id)
            if channel is None:
                print(f"⚠️ Canal {channel_id} no encontrado o no accesible")
                continue

            embed = discord.Embed(
                title=config["title"],
                description=config["description"],
                color=int(config["color"].replace("#", ""), 16)
            )

            if config.get("image_url"):
                embed.set_image(url=config["image_url"])
            if config.get("thumbnail_url"):
                embed.set_thumbnail(url=config["thumbnail_url"])
            if config.get("footer_text") or config.get("footer_icon_url"):
                embed.set_footer(
                    text=config.get("footer_text") or None,
                    icon_url=config.get("footer_icon_url") or None
                )
            if config.get("author_name"):
                embed.set_author(
                    name=config["author_name"],
                    icon_url=config.get("author_icon_url") or None
                )
            if config.get("use_timestamp"):
                embed.timestamp = datetime.utcnow()

            sticky_embeds[channel_id] = embed

            # Intentar borrar sticky anterior si existe
            last_message_id = config.get("last_message_id")
            if last_message_id:
                await try_delete_message(channel, int(last_message_id))

            # Enviar nuevo sticky
            sent = await channel.send(embed=embed)
            sticky_messages[channel_id] = sent

            # Guardar el nuevo last_message_id
            sticky_config_data[channel_id_str]["last_message_id"] = sent.id
            save_stickies(sticky_config_data)

            print(f"✅ Sticky cargado y enviado para canal {channel_id}")

        except Exception as e:
            print(f"⚠️ Error al cargar sticky para canal {channel_id_str}: {e}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    channel = message.channel
    channel_id = channel.id

    if channel_id not in sticky_embeds:
        return

    # Cancelar tarea pendiente si existe
    if channel_id in pending_sticky_tasks:
        pending_sticky_tasks[channel_id].cancel()

    async def delayed_sticky():
        try:
            await asyncio.sleep(STICKY_DELAY_SECONDS)
            embed = sticky_embeds[channel_id]

            # Borrar sticky anterior si existe
            if channel_id in sticky_messages:
                try:
                    await sticky_messages[channel_id].delete()
                    print(f"🗑️ Mensaje sticky anterior borrado en canal {channel_id}")
                except discord.NotFound:
                    pass

            sent = await channel.send(embed=embed)
            sticky_messages[channel_id] = sent

            # Actualizar last_message_id en config y guardar
            sticky_config_data[str(channel_id)]["last_message_id"] = sent.id
            save_stickies(sticky_config_data)

            print(f"📨 Sticky reenviado en canal {channel_id}")

        except asyncio.CancelledError:
            # Tarea cancelada, no pasa nada
            pass
        except Exception as e:
            print(f"❌ Error reenviando sticky en canal {channel_id}: {e}")

    pending_sticky_tasks[channel_id] = asyncio.create_task(delayed_sticky())

@bot.tree.command(name="setsticky", description="Configura un sticky embed personalizado para este canal")
@discord.app_commands.describe(
    title="Título del embed",
    description="Descripción del embed",
    color="Color en HEX (ej: #ff0000)",
    image_url="URL de imagen (opcional)",
    thumbnail_url="URL del thumbnail (opcional)",
    footer_text="Texto del footer (opcional)",
    footer_icon_url="Icono del footer (opcional)",
    author_name="Nombre del autor (opcional)",
    author_icon_url="URL del ícono del autor (opcional)",
    use_timestamp="¿Mostrar hora actual en el footer?"
)
async def setsticky(
    interaction: discord.Interaction,
    title: str,
    description: str,
    color: str,
    image_url: str = None,
    thumbnail_url: str = None,
    footer_text: str = None,
    footer_icon_url: str = None,
    author_name: str = None,
    author_icon_url: str = None,
    use_timestamp: bool = False
):
    await interaction.response.defer(thinking=True, ephemeral=True)

    try:
        embed_color = int(color.replace("#", ""), 16)

        embed = discord.Embed(
            title=title,
            description=description,
            color=embed_color
        )

        if image_url:
            embed.set_image(url=image_url)

        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)

        if footer_text or footer_icon_url:
            embed.set_footer(
                text=footer_text or None,
                icon_url=footer_icon_url or None
            )

        if use_timestamp:
            embed.timestamp = datetime.utcnow()

        if author_name:
            embed.set_author(
                name=author_name,
                icon_url=author_icon_url if author_icon_url else None
            )

        channel_id = interaction.channel_id
        sticky_embeds[channel_id] = embed

        # Guardar configuración (resetear last_message_id para evitar conflicto)
        sticky_config_data[str(channel_id)] = {
            "title": title,
            "description": description,
            "color": color,
            "image_url": image_url,
            "thumbnail_url": thumbnail_url,
            "footer_text": footer_text,
            "footer_icon_url": footer_icon_url,
            "author_name": author_name,
            "author_icon_url": author_icon_url,
            "use_timestamp": use_timestamp,
            "last_message_id": None  # Se actualizará al enviar
        }
        save_stickies(sticky_config_data)

        await interaction.followup.send("✅ Sticky configurado. Se enviará después de un breve período de inactividad en el canal.")
    except Exception as e:
        await interaction.followup.send(f"❌ Error al crear el embed: {e}")


# Componente para paginar la lista de stickies
class StickyListView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.index = 0

    def get_channel_ids(self):
        return list(sticky_embeds.keys())

    async def update_message(self, interaction: Interaction):
        channel_ids = self.get_channel_ids()

        # Ajustar índice si el número de stickies cambió
        if self.index >= len(channel_ids):
            self.index = max(0, len(channel_ids) - 1)

        channel_id = channel_ids[self.index]
        embed = sticky_embeds.get(channel_id)
        if not embed:
            embed = Embed(description="⚠️ Embed no encontrado para este canal.")

        content = f"Sticky {self.index + 1} de {len(channel_ids)} - Canal ID: <#{channel_id}>"
        await interaction.response.edit_message(content=content, embed=embed, view=self)

    @ui.button(label="Anterior", style=ButtonStyle.secondary)
    async def prev_button(self, interaction: Interaction, button: ui.Button):
        channel_ids = self.get_channel_ids()
        self.index = (self.index - 1) % len(channel_ids)
        await self.update_message(interaction)

    @ui.button(label="Siguiente", style=ButtonStyle.secondary)
    async def next_button(self, interaction: Interaction, button: ui.Button):
        channel_ids = self.get_channel_ids()
        self.index = (self.index + 1) % len(channel_ids)
        await self.update_message(interaction)

    @ui.button(label="Forzar sticky", style=ButtonStyle.primary)
    async def force_button(self, interaction: Interaction, button: ui.Button):
        channel_ids = self.get_channel_ids()
        channel_id = channel_ids[self.index]
        channel = bot.get_channel(channel_id)
        if channel is None:
            await interaction.response.send_message("⚠️ No puedo acceder a este canal.", ephemeral=True)
            return

        embed = sticky_embeds.get(channel_id)
        if not embed:
            await interaction.response.send_message("⚠️ No hay sticky configurado para este canal.", ephemeral=True)
            return

        # Borrar sticky anterior si existe
        if channel_id in sticky_messages:
            try:
                await sticky_messages[channel_id].delete()
            except discord.NotFound:
                pass
            except discord.Forbidden:
                await interaction.response.send_message("❌ No tengo permiso para borrar el mensaje sticky.", ephemeral=True)
                return

        sent = await channel.send(embed=embed)
        sticky_messages[channel_id] = sent

        sticky_config_data[str(channel_id)]["last_message_id"] = sent.id
        save_stickies(sticky_config_data)

        await interaction.response.send_message("✅ Sticky reenviado correctamente.", ephemeral=True)

    @ui.button(label="Borrar sticky", style=ButtonStyle.danger)
    async def delete_button(self, interaction: Interaction, button: ui.Button):
        channel_ids = self.get_channel_ids()
        channel_id = channel_ids[self.index]
        channel = bot.get_channel(channel_id)
        if channel is None:
            await interaction.response.send_message("⚠️ No puedo acceder a este canal.", ephemeral=True)
            return

        last_msg_id = sticky_config_data.get(str(channel_id), {}).get("last_message_id")
        if last_msg_id:
            try:
                msg = await channel.fetch_message(last_msg_id)
                await msg.delete()
            except discord.NotFound:
                pass
            except discord.Forbidden:
                await interaction.response.send_message("❌ No tengo permiso para borrar el mensaje sticky.", ephemeral=True)
                return

        # Eliminar la configuración del sticky
        sticky_config_data.pop(str(channel_id), None)
        sticky_embeds.pop(channel_id, None)
        sticky_messages.pop(channel_id, None)
        save_stickies(sticky_config_data)

        # Actualizar la lista
        if self.index >= len(channel_ids) - 1 and self.index > 0:
            self.index -= 1

        if not self.get_channel_ids():
            await interaction.response.edit_message(content="✅ No quedan stickies configurados.", embed=None, view=None)
            return

        await self.update_message(interaction)




#@bot.tree.command(name="listarstickies", description="Muestra la lista de stickies configurados con vista previa y botón para borrar")
#async def listarstickies(interaction: discord.Interaction):
    #if not sticky_embeds:
        #await interaction.response.send_message("⚠️ No hay stickies configurados en ningún canal.", ephemeral=True)
        #return

    #channel_ids = list(sticky_embeds.keys())
    #view = StickyListView(channel_ids)

    #first_embed = sticky_embeds[channel_ids[0]]
    #content = f"Sticky 1 de {len(channel_ids)} - Canal ID: <#{channel_ids[0]}>"

    #await interaction.response.send_message(content=content, embed=first_embed, view=view, ephemeral=True)


@bot.tree.command(name="listarstickies", description="Muestra la lista de stickies configurados con vista previa y botón para borrar")
async def listarstickies(interaction: discord.Interaction):
    admin_channel_id = 1351290702755270884  # Reemplaza con el ID de tu canal admin
    admin_channel = bot.get_channel(admin_channel_id)

    if not sticky_embeds:
        await interaction.response.send_message("⚠️ No hay stickies configurados en ningún canal.", ephemeral=True)
        return

    if admin_channel is None:
        await interaction.response.send_message("❌ No puedo encontrar el canal de administración configurado.", ephemeral=True)
        return

    view = StickyListView()

    channel_ids = list(sticky_embeds.keys())
    first_embed = sticky_embeds[channel_ids[0]]
    content = f"Sticky 1 de {len(channel_ids)} - Canal ID: <#{channel_ids[0]}>"


    # Enviar mensaje al canal admin con embed y botones
    await admin_channel.send(content=content, embed=first_embed, view=view)

    # Responder al usuario que ejecutó el comando con mensaje ephemeral
    await interaction.response.send_message(content=content, embed=first_embed, view=view, ephemeral=True)






bot.run(os.getenv("DISCORD_TOKEN"))
