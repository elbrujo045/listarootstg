import os
import asyncio
import logging
import datetime
import json
import random
from datetime import timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest, Forbidden

from flask import Flask
from threading import Thread

# --- Configuração de Log ---
# Essencial para ver o que o bot está fazendo nos bastidores
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG # MANTENHA COMO DEBUG para depuração completa
)
logger = logging.getLogger(__name__)

# --- Variáveis Globais (Carregadas ou Definidas) ---
# Use o token do bot da variável de ambiente ou substitua diretamente (NÃO RECOMENDADO EM PRODUÇÃO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "7452415037:AAHPYwIeI_2TAXCUHxcKcaZfSPX7E7Nv7eg")
if BOT_TOKEN == "SEU_TOKEN_DO_BOT_AQUI":
    logger.critical("ATENÇÃO: BOT_TOKEN não configurado! Por favor, defina a variável de ambiente BOT_TOKEN.")

bot_data = {} # Dicionário para armazenar dados persistentes
DATA_FILE = 'bot_data.json' # Arquivo para persistir os dados

ADMIN_CHAT_ID = None # Será definido pelo comando /start pelo primeiro usuário

# --- Funções de Persistência de Dados ---
def load_data():
    global bot_data, ADMIN_CHAT_ID
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            loaded_data = json.load(f)
            # Converte chaves de volta para int se necessário (chat_ids são strings para chaves de JSON)
            # Garante que as estruturas básicas existam para evitar KeyError
            bot_data['canais_e_grupos'] = {int(k): v for k, v in loaded_data.get('canais_e_grupos', {}).items()}
            bot_data['agendamentos'] = {int(k): v for k, v in loaded_data.get('agendamentos', {}).items()}
            bot_data['cabecalho_texto'] = loaded_data.get('cabecalho_texto', "✨ **Confira essas listas de canais e grupos no Telegram!** ✨")
            bot_data['cabecalho_media_id'] = loaded_data.get('cabecalho_media_id', None)
            bot_data['cabecalho_media_type'] = loaded_data.get('cabecalho_media_type', None)
            ADMIN_CHAT_ID = loaded_data.get('ADMIN_CHAT_ID')
            logger.info("Dados do bot carregados com sucesso.")
            if ADMIN_CHAT_ID:
                logger.info(f"ADMIN_CHAT_ID carregado: {ADMIN_CHAT_ID}")
    else:
        # Inicializa com valores padrão se o arquivo não existir
        bot_data.setdefault('canais_e_grupos', {})
        bot_data.setdefault('agendamentos', {})
        bot_data.setdefault('cabecalho_texto', "✨ **Confira essas listas de canais e grupos no Telegram!** ✨")
        bot_data.setdefault('cabecalho_media_id', None)
        bot_data.setdefault('cabecalho_media_type', None)
        logger.info("Arquivo de dados não encontrado. Iniciando com dados padrão.")

def save_data():
    # Converte chaves de int para string para salvar em JSON
    data_to_save = bot_data.copy()
    data_to_save['canais_e_grupos'] = {str(k): v for k, v in bot_data.get('canais_e_grupos', {}).items()}
    data_to_save['agendamentos'] = {str(k): v for k, v in bot_data.get('agendamentos', {}).items()}

    with open(DATA_FILE, 'w') as f:
        json.dump(data_to_save, f, indent=4)
    logger.info("Dados do bot salvos com sucesso.")

# --- Funções do Flask para Keep-Alive ---
app = Flask(__name__)

@app.route('/')
def hello_world():
    """Endpoint simples para o Render verificar se a aplicação está viva."""
    return 'Bot is alive!'

def run_flask():
    """Inicia o servidor Flask."""
    port = int(os.environ.get('PORT', 8080))
    # Desativa o reloader e debug para produção
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def keep_alive():
    """Inicia o servidor Flask em uma thread separada."""
    t = Thread(target=run_flask)
    t.start()
    logger.info(f"Servidor Flask de Keep-Alive iniciado na porta {os.environ.get('PORT', 8080)}.")


# --- Funções de Agendamento ---
async def send_daily_posts(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia as publicações agendadas para todos os canais/grupos cadastrados."""
    logger.info("Iniciando o envio de posts diários.")
    canais_cadastrados = list(bot_data.get('canais_e_grupos', {}).keys())
    random.shuffle(canais_cadastrados) # Opcional: embaralhar a ordem
    
    if not canais_cadastrados:
        logger.info("Nenhum canal ou grupo cadastrado para envio.")
        if ADMIN_CHAT_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text="⚠️ Não há canais/grupos cadastrados para o envio agendado. ⚠️",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Erro ao enviar mensagem de aviso ao admin: {e}")
        return

    cabecalho = bot_data.get('cabecalho_texto', "✨ **Confira essas listas de canais e grupos no Telegram!** ✨")
    media_id = bot_data.get('cabecalho_media_id')
    media_type = bot_data.get('cabecalho_media_type')

    # Cria a lista de links
    links_mensagem = "\n\n"
    for chat_id_int, info in bot_data['canais_e_grupos'].items():
        links_mensagem += f"➡️ {info.get('link', info.get('nome', 'Canal/Grupo Desconhecido'))}\n"
    
    # Monta a mensagem completa
    full_message = f"{cabecalho}{links_mensagem}"

    sucessos = 0
    falhas = 0
    falhas_detalhes = []
    canais_para_remover = []

    for chat_id_int in canais_cadastrados:
        try:
            logger.debug(f"Tentando enviar para o canal/grupo: {chat_id_int}")
            
            if media_id and media_type:
                if media_type == 'photo':
                    await context.bot.send_photo(chat_id=chat_id_int, photo=media_id, caption=full_message, parse_mode='Markdown')
                elif media_type == 'video':
                    await context.bot.send_video(chat_id=chat_id_int, video=media_id, caption=full_message, parse_mode='Markdown')
                elif media_type == 'animation':
                    await context.bot.send_animation(chat_id=chat_id_int, animation=media_id, caption=full_message, parse_mode='Markdown')
            else:
                await context.bot.send_message(chat_id=chat_id_int, text=full_message, parse_mode='Markdown', disable_web_page_preview=True)
            
            sucessos += 1
            logger.debug(f"Envio bem-sucedido para {chat_id_int}")

        except Forbidden:
            falhas += 1
            chat_name = bot_data['canais_e_grupos'].get(chat_id_int, {}).get('nome', 'Desconhecido')
            falhas_detalhes.append(f"- **{chat_name}** (`{chat_id_int}`): Bot foi bloqueado ou removido. (Removido da lista)")
            logger.warning(f"Bot foi bloqueado ou removido do chat: {chat_id_int}. Marcando para remoção.")
            canais_para_remover.append(chat_id_int) # Adiciona o ID inteiro para remoção
        except BadRequest as e:
            falhas += 1
            chat_name = bot_data['canais_e_grupos'].get(chat_id_int, {}).get('nome', 'Desconhecido')
            falhas_detalhes.append(f"- **{chat_name}** (`{chat_id_int}`): Erro de requisição ({e}).")
            logger.error(f"Erro de BadRequest ao enviar para {chat_id_int}: {e}")
        except Exception as e:
            falhas += 1
            chat_name = bot_data['canais_e_grupos'].get(chat_id_int, {}).get('nome', 'Desconhecido')
            falhas_detalhes.append(f"- **{chat_name}** (`{chat_id_int}`): Erro inesperado ({e}).")
            logger.error(f"Erro inesperado ao enviar para {chat_id_int}: {e}", exc_info=True)

    # Remove os canais que causaram Forbidden APÓS o loop de envio
    for chat_id_int_to_remove in canais_para_remover:
        if chat_id_int_to_remove in bot_data['canais_e_grupos']:
            del bot_data['canais_e_grupos'][chat_id_int_to_remove]
    save_data() # Salva dados após todas as remoções

    summary_message = f"**Relatório de Envio Diário:**\n" \
                      f"✅ Sucessos: {sucessos}\n" \
                      f"❌ Falhas: {falhas}\n"
    if falhas > 0:
        summary_message += "\n**Detalhes das Falhas:**\n" + "\n".join(falhas_detalhes)
        
    logger.info(f"Relatório de envio diário: Sucessos={sucessos}, Falhas={falhas}")
    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=summary_message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Erro ao enviar relatório de envio ao admin: {e}")


async def agendar_daily_jobs_on_startup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Agenda os jobs diários com base nos horários configurados."""
    if not ADMIN_CHAT_ID:
        logger.warning("Não há ADMIN_CHAT_ID definido. Não é possível agendar trabalhos.")
        return

    agenda_info = bot_data['agendamentos'].get(ADMIN_CHAT_ID, {}) # Usar ADMIN_CHAT_ID como int
    horarios_str = agenda_info.get('horarios', [])
    ativo = agenda_info.get('ativo', False)

    # Remove todos os jobs antigos para evitar duplicações
    current_jobs = context.job_queue.get_jobs_by_name("daily_post_job")
    for job in current_jobs:
        job.schedule_removal()
        logger.debug(f"Job existente 'daily_post_job' removido: {job.next_run_time}")

    if not ativo or not horarios_str:
        logger.info("Agendamento desativado ou sem horários definidos para o admin. Nenhum job será agendado.")
        if ADMIN_CHAT_ID and ADMIN_CHAT_ID in bot_data['agendamentos'] and bot_data['agendamentos'][ADMIN_CHAT_ID].get('ativo'):
             try:
                 await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="Agendamento desativado ou sem horários. Jobs anteriores removidos.")
             except Exception as e:
                 logger.error(f"Erro ao enviar mensagem de desativação de agendamento ao admin: {e}")
        return

    for horario_str in horarios_str:
        try:
            h = datetime.time.fromisoformat(horario_str)
            context.job_queue.run_daily(
                send_daily_posts,
                time=h,
                days=tuple(range(7)),  # Todos os dias da semana
                data={'admin_id': ADMIN_CHAT_ID},
                name="daily_post_job"
            )
            logger.info(f"Job 'daily_post_job' agendado para {horario_str} (fuso horário do servidor).")
        except ValueError:
            logger.error(f"Horário inválido '{horario_str}' no agendamento. Ignorando.")


# --- Handlers de Comandos ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia uma mensagem de boas-vindas e define o ADMIN_CHAT_ID se for o primeiro."""
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    user_name = update.message.from_user.first_name

    global ADMIN_CHAT_ID # Indica que estamos modificando a variável global

    if ADMIN_CHAT_ID is None:
        ADMIN_CHAT_ID = chat_id
        bot_data['ADMIN_CHAT_ID'] = chat_id
        save_data()
        logger.info(f"ADMIN_CHAT_ID definido como {chat_id} por {user_name}.")
        await update.message.reply_text(
            f"Olá, {user_name}! Você foi definido como o administrador deste bot.\n\n"
            "Use /ajuda para ver os comandos disponíveis."
        )
        # Tenta agendar jobs se já houver horários configurados para o novo admin
        await agendar_daily_jobs_on_startup(context)
    elif chat_id == ADMIN_CHAT_ID:
        await update.message.reply_text(
            f"Bem-vindo de volta, {user_name}! Você é o administrador.\n"
            "Use /ajuda para ver os comandos disponíveis."
        )
    else:
        await update.message.reply_text(
            f"Olá, {user_name}! Eu sou um bot de divulgação de canais e grupos. "
            "Se você é o proprietário e deseja cadastrar seu canal/grupo para divulgação, use o comando /cadastrar.\n\n"
            "Se você não é o administrador, por favor, entre em contato com o dono do bot para mais informações."
        )

async def cadastrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Solicita o link do canal/grupo para cadastro."""
    context.user_data['estado'] = 'aguardando_link_cadastro'
    context.user_data['user_id_cadastro'] = update.message.from_user.id # Guarda o ID do usuário que pediu o cadastro
    await update.message.reply_text(
        "Por favor, envie o link de convite do seu canal ou grupo (ex: `https://t.me/seucanal` ou `https://t.me/+ABCDEFGH`).\n"
        "Certifique-se de que o link é de convite e está no formato `t.me/` ou `telegram.me/`.\n"
        "Envie /cancelar para abortar a qualquer momento."
        , parse_mode='Markdown'
    )

async def ver_canais_e_grupos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe a lista de canais e grupos cadastrados."""
    # update pode ser Message ou CallbackQuery, precisamos adaptar
    message = update.message if update.message else update.callback_query.message

    if message.chat.id != ADMIN_CHAT_ID:
        await message.reply_text("Desculpe, este comando é apenas para administradores.")
        return

    canais = bot_data.get('canais_e_grupos', {})
    if not canais:
        await message.reply_text("Nenhum canal ou grupo cadastrado ainda.")
        return

    mensagem = "Canais e Grupos Cadastrados:\n\n"
    for chat_id_int, info in canais.items(): # Itera sobre inteiros
        mensagem += (
            f"**Nome:** `{info.get('nome', 'N/A')}`\n"
            f"**Tipo:** `{info.get('tipo', 'N/A')}`\n"
            f"**Membros:** `{info.get('membros', 'N/A')}`\n"
            f"**Link:** {info.get('link', 'Não disponível')}\n"
            f"**ID:** `{chat_id_int}`\n\n" # Exibe o ID como inteiro
        )
    await message.reply_text(mensagem, parse_mode='Markdown')

# Novo comando para iniciar o fluxo de edição do cabeçalho
async def editar_cabecalho(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o fluxo de edição do cabeçalho com opções de botões."""
    message = update.message if update.message else update.callback_query.message
    if message.chat.id != ADMIN_CHAT_ID:
        await message.reply_text("Desculpe, este comando é apenas para administradores.")
        return

    keyboard = [
        [InlineKeyboardButton("Editar Texto", callback_data="edit_header_text")],
        [InlineKeyboardButton("Editar Mídia (Foto/GIF/Vídeo)", callback_data="edit_header_media")],
        [InlineKeyboardButton("Remover Mídia do Cabeçalho", callback_data="remove_header_media")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply_text(
        "O que você gostaria de editar no cabeçalho da sua lista de divulgação?",
        reply_markup=reply_markup
    )

async def agendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o processo de agendamento de posts diários."""
    message = update.message if update.message else update.callback_query.message
    if message.chat.id != ADMIN_CHAT_ID:
        await message.reply_text("Desculpe, este comando é apenas para administradores.")
        return
    context.user_data['estado'] = 'aguardando_horarios_agendamento'
    current_schedule_info = bot_data['agendamentos'].get(ADMIN_CHAT_ID, {})
    current_horarios = current_schedule_info.get('horarios', [])
    status_agenda = "Ativo" if current_schedule_info.get('ativo', False) else "Inativo"
    
    await message.reply_text(
        f"Por favor, envie os horários para agendamento diário (formato HH:MM, separados por vírgula).\n"
        f"Ex: `09:00, 15:30, 21:00`\n\n"
        f"Agendamentos atuais: {', '.join(current_horarios) if current_horarios else 'Nenhum'}\n"
        f"Status: {status_agenda}\n"
        "Envie /cancelar para abortar."
    )

async def parar_agendamento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Para o agendamento de posts diários."""
    message = update.message if update.message else update.callback_query.message
    if message.chat.id != ADMIN_CHAT_ID:
        await message.reply_text("Desculpe, este comando é apenas para administradores.")
        return
    if ADMIN_CHAT_ID and ADMIN_CHAT_ID in bot_data['agendamentos']:
        bot_data['agendamentos'][ADMIN_CHAT_ID]['ativo'] = False
        save_data()
        await agendar_daily_jobs_on_startup(context) # Re-agendará, desativando os jobs
        await message.reply_text("Agendamento de posts diários pausado.")
    else:
        await message.reply_text("Nenhum agendamento ativo para pausar.")

async def retomar_agendamento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retoma o agendamento de posts diários."""
    message = update.message if update.message else update.callback_query.message
    if message.chat.id != ADMIN_CHAT_ID:
        await message.reply_text("Desculpe, este comando é apenas para administradores.")
        return
    if ADMIN_CHAT_ID and ADMIN_CHAT_ID in bot_data['agendamentos']:
        if bot_data['agendamentos'][ADMIN_CHAT_ID].get('horarios'):
            bot_data['agendamentos'][ADMIN_CHAT_ID]['ativo'] = True
            save_data()
            await agendar_daily_jobs_on_startup(context) # Re-agendará, ativando os jobs
            await message.reply_text("Agendamento de posts diários retomado.")
        else:
            await message.reply_text("Não há horários agendados para retomar. Use /agendar primeiro.")
    else:
        await message.reply_text("Nenhum agendamento configurado para retomar. Use /agendar primeiro.")

async def testar_envio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Testa o envio de uma publicação para os canais/grupos cadastrados."""
    message = update.message if update.message else update.callback_query.message
    if message.chat.id != ADMIN_CHAT_ID:
        await message.reply_text("Desculpe, este comando é apenas para administradores.")
        return
    await message.reply_text("Testando o envio de publicação para os canais/grupos cadastrados...")
    await send_daily_posts(context)
    await message.reply_text("Teste de envio concluído. Verifique o relatório no seu chat (se houver falhas).")

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra os comandos disponíveis, com botões para administradores."""
    # update pode vir de Message ou CallbackQuery, precisamos adaptar para enviar a resposta
    message_to_reply = update.message if update.message else update.callback_query.message
    user_chat_id = message_to_reply.chat.id

    help_message = (
        "Comandos disponíveis:\n\n"
        "🌐 **Para todos os usuários:**\n"
        "/start - Inicia o bot e me define como administrador (se for o primeiro a usar).\n"
        "/cadastrar - Inicia o processo de cadastro do seu canal/grupo para divulgação.\n"
        "/ajuda - Mostra esta mensagem de ajuda.\n"
        "/cancelar - Cancela qualquer operação atual (cadastro, edição, agendamento).\n\n"
    )

    keyboard = []
    reply_markup = None

    if user_chat_id == ADMIN_CHAT_ID:
        help_message += "👑 **Comandos de Administrador (apenas para você):**\n"
        
        # Cria os botões para os comandos de administrador
        keyboard.append([InlineKeyboardButton("Ver Canais Cadastrados", callback_data="admin_ver_canais")])
        keyboard.append([InlineKeyboardButton("Editar Cabeçalho", callback_data="admin_editar_cabecalho")]) # Novo botão
        keyboard.append([InlineKeyboardButton("Agendar Publicações", callback_data="admin_agendar")])
        keyboard.append([InlineKeyboardButton("Parar Agendamento", callback_data="admin_parar_agendamento")])
        keyboard.append([InlineKeyboardButton("Retomar Agendamento", callback_data="admin_retomar_agendamento")])
        keyboard.append([InlineKeyboardButton("Testar Envio Agora", callback_data="admin_testar_envio")])
        keyboard.append([InlineKeyboardButton("Remover Canal", callback_data="admin_remover_canal")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Envia a mensagem de ajuda e, se for admin, os botões
    await message_to_reply.reply_text(help_message, reply_markup=reply_markup, parse_mode='Markdown')

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancela a operação atual."""
    message = update.message if update.message else update.callback_query.message
    if 'estado' in context.user_data:
        del context.user_data['estado']
        await message.reply_text("Operação cancelada.")
    else:
        await message.reply_text("Nenhuma operação em andamento para cancelar.")

async def remover_canal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o processo de remoção de um canal/grupo."""
    message = update.message if update.message else update.callback_query.message
    if message.chat.id != ADMIN_CHAT_ID:
        await message.reply_text("Desculpe, este comando é apenas para administradores.")
        return

    canais = bot_data.get('canais_e_grupos', {})
    if not canais:
        await message.reply_text("Nenhum canal ou grupo cadastrado para remover.")
        return

    keyboard = []
    # Usar o ID inteiro para o callback_data para consistência
    for chat_id_int, info in canais.items():
        keyboard.append([InlineKeyboardButton(info.get('nome', f"ID: {chat_id_int}"), callback_data=f"remove_chat_{chat_id_int}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(
        "Selecione o canal/grupo que deseja remover:",
        reply_markup=reply_markup
    )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa as chamadas de retorno de botões inline."""
    query = update.callback_query
    await query.answer() # Sempre responda à callback_query para remover o "carregando" do botão

    # Verificação de segurança: Apenas o ADMIN_CHAT_ID pode usar os botões de administrador
    # (Ou botões que ele iniciou, como remover_canal)
    if query.message.chat.id != ADMIN_CHAT_ID and not query.data.startswith('remove_chat_'):
        # Permite que não-admins cliquem em botões de remoção que o admin gerou
        await query.edit_message_text("Desculpe, esta ação é apenas para administradores.")
        return

    if query.data.startswith('remove_chat_'):
        # Note: o ID no callback_data vem como string. Converter para int para buscar no bot_data.
        chat_id_to_remove = int(query.data.replace('remove_chat_', ''))
        
        if chat_id_to_remove in bot_data['canais_e_grupos']:
            removed_name = bot_data['canais_e_grupos'][chat_id_to_remove]['nome']
            del bot_data['canais_e_grupos'][chat_id_to_remove]
            save_data()
            await query.edit_message_text(f"Canal/grupo **'{removed_name}'** (`{chat_id_to_remove}`) removido com sucesso da lista.", parse_mode='Markdown')
            logger.info(f"Canal/grupo '{removed_name}' ({chat_id_to_remove}) removido pelo admin.")
        else:
            await query.edit_message_text("Canal/grupo não encontrado na lista.")

    # --- Lógicas para os botões de ADMIN ---
    elif query.data == 'admin_ver_canais':
        await query.edit_message_text("Carregando lista de canais...")
        await ver_canais_e_grupos(update, context) # Passa update completo para a função
    
    elif query.data == 'admin_editar_cabecalho': # Novo callback para o fluxo de edição
        await query.edit_message_text("Iniciando edição do cabeçalho...")
        await editar_cabecalho(update, context)

    elif query.data == 'admin_agendar':
        await query.edit_message_text("Iniciando configuração de agendamento...")
        await agendar(update, context)

    elif query.data == 'admin_parar_agendamento':
        await query.edit_message_text("Pausando agendamento...")
        await parar_agendamento(update, context)

    elif query.data == 'admin_retomar_agendamento':
        await query.edit_message_text("Retomando agendamento...")
        await retomar_agendamento(update, context)

    elif query.data == 'admin_testar_envio':
        await query.edit_message_text("Testando envio...")
        await testar_envio(update, context)

    elif query.data == 'admin_remover_canal':
        await query.edit_message_text("Preparando remoção de canal...")
        await remover_canal(update, context)
    
    # --- Callbacks para o fluxo de edição de cabeçalho ---
    elif query.data == 'edit_header_text':
        context.user_data['estado'] = 'aguardando_texto_cabecalho_fluxo'
        await query.edit_message_text(
            f"Por favor, envie o novo texto para o cabeçalho. O texto atual é:\n\n`{bot_data.get('cabecalho_texto', 'Nenhum')}`\n\n"
            "Você pode usar formatação Markdown (ex: **negrito**, _itálico_)."
            "Envie /cancelar para abortar."
        , parse_mode='Markdown')

    elif query.data == 'edit_header_media':
        context.user_data['estado'] = 'aguardando_media_cabecalho_fluxo'
        await query.edit_message_text(
            "Por favor, envie a nova foto, GIF ou vídeo para o cabeçalho. "
            "A mídia atual será substituída. Envie /cancelar para abortar."
        )
    
    elif query.data == 'remove_header_media':
        bot_data['cabecalho_media_id'] = None
        bot_data['cabecalho_media_type'] = None
        save_data()
        await query.edit_message_text("Mídia do cabeçalho removida com sucesso!")
        logger.info(f"Mídia do cabeçalho removida pelo admin {ADMIN_CHAT_ID}.")


# --- Handlers de Mensagens ---

async def handle_text_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lida com respostas de texto baseadas no estado do usuário."""
    if not update.message or not update.message.text: 
        logger.warning("handle_text_response chamada sem update.message ou sem texto. Ignorando.")
        return

    user_chat_id = update.message.chat_id
    current_state = context.user_data.get('estado')

    # Lida com o estado de cadastro de link (acessível a qualquer um)
    if current_state == 'aguardando_link_cadastro':
        link = update.message.text.strip() # Remove espaços em branco
        logger.debug(f"DEBUG: Link recebido para cadastro: '{link}' (Tipo: {type(link)}, Comprimento: {len(link)})")

        if link and ("t.me/" in link or "telegram.me/" in link):
            # Validação mais rigorosa para links de convite
            if not (link.startswith("https://t.me/") or link.startswith("http://t.me/") or \
                    link.startswith("https://telegram.me/") or link.startswith("http://telegram.me/") or \
                    link.startswith("t.me/") or link.startswith("telegram.me/")): # Adicionado sem https/http
                await update.message.reply_text(
                    "O link parece ser do Telegram, mas não está no formato esperado (ex: `https://t.me/seucanal` ou `t.me/seucanal`). Por favor, use o link de convite completo."
                , parse_mode='Markdown')
                return # Não limpa o estado, espera nova entrada
            
            # Normaliza o link para ter https:// se não tiver
            if not link.startswith("http"):
                link = "https://" + link

            context.user_data['cadastrando_link'] = link # Armazena o link temporariamente
            await update.message.reply_text(
                f"Link recebido: `{link}`. Agora, por favor, me adicione como **administrador** no seu canal/grupo. "
                "Assim que eu for adicionado, enviarei uma mensagem de confirmação e adicionarei o canal/grupo à lista.\n"
                "**Permissões necessárias para mim:**\n"
                "- **Administrador completo** (ou, no mínimo, 'Postar mensagens' e 'Adicionar membros').\n"
                "- `Postar mensagens` (para que eu possa publicar a lista).\n"
                "- `Adicionar membros` (para que eu possa verificar a contagem de membros se for um link privado/convite).\n"
                "\n*Obs: Seu canal/grupo deve ter 50 membros ou mais para ser adicionado.*",
                parse_mode='Markdown')
            # Não remove o estado aqui. O estado é removido por new_chat_members quando o bot é adicionado.
            # Se o bot não for adicionado, o usuário pode tentar novamente ou cancelar.
            logger.debug(f"DEBUG: Link '{link}' armazenado em context.user_data para {user_chat_id}. Estado 'aguardando_link_cadastro' mantido.")
        else:
            await update.message.reply_text(
                "Parece que não é um link válido do Telegram. Por favor, tente novamente. O link deve começar com `t.me/` ou `telegram.me/`."
            )
    # Lida com estados de admin
    elif user_chat_id == ADMIN_CHAT_ID:
        if current_state == 'aguardando_texto_cabecalho_fluxo':
            bot_data['cabecalho_texto'] = update.message.text
            await update.message.reply_text(
                f"Texto do cabeçalho atualizado para:\n`{bot_data['cabecalho_texto']}`",
                parse_mode='Markdown')
            save_data()
            context.user_data.pop('estado')
        elif current_state == 'aguardando_horarios_agendamento':
            horarios_str_input = update.message.text
            horarios_validos = []
            erros_horario = []
            for h in horarios_str_input.split(','):
                h_stripped = h.strip()
                try:
                    datetime.time.fromisoformat(h_stripped)
                    horarios_validos.append(h_stripped)
                except ValueError:
                    erros_horario.append(h_stripped)
            
            if erros_horario:
                await update.message.reply_text(
                    f"Horário(s) inválido(s) encontrado(s): `{', '.join(erros_horario)}`. Por favor, use o formato HH:MM (ex: 09:00, 15:30) e tente novamente."
                , parse_mode='Markdown')
                return # Não limpa o estado, espera nova entrada
            
            if not horarios_validos:
                await update.message.reply_text(
                    "Nenhum horário válido fornecido. Por favor, tente novamente."
                )
                return # Não limpa o estado, espera nova entrada

            bot_data['agendamentos'][ADMIN_CHAT_ID] = { # Salva com ADMIN_CHAT_ID como int
                'horarios': horarios_validos,
                'ativo': True
            }
            await update.message.reply_text(
                f"Agendamentos configurados para os seguintes horários: {', '.join(horarios_validos)}\n"
                "As publicações ocorrerão diariamente nestes horários."
            )
            save_data()
            context.user_data.pop('estado')
            await agendar_daily_jobs_on_startup(context) # Re-agenda com os novos horários
        else:
            # Estado de admin não reconhecido
            await update.message.reply_text("Desculpe, um estado inesperado foi encontrado. Tente novamente ou use /cancelar.")
            logger.warning(f"Estado de admin '{current_state}' não tratado em handle_text_response para {user_chat_id}.")
    else:
        # Resposta padrão para mensagens de texto que não são comandos ou estados esperados
        await update.message.reply_text("Desculpe, não entendi o que você quis dizer. Use /ajuda para ver os comandos disponíveis.")


async def handle_media_cabecalho(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lida com o envio de mídia para o cabeçalho."""
    if not update.message:
        logger.warning("handle_media_cabecalho foi chamada, mas update.message é None. Ignorando a atualização.")
        return

    user_chat_id = update.message.chat_id
    current_state = context.user_data.get('estado')

    if user_chat_id == ADMIN_CHAT_ID and current_state == 'aguardando_media_cabecalho_fluxo':
        if update.message.photo:
            bot_data['cabecalho_media_id'] = update.message.photo[-1].file_id # Pega a maior resolução
            bot_data['cabecalho_media_type'] = 'photo'
            await update.message.reply_text("Imagem do cabeçalho atualizada com sucesso!")
            save_data()
        elif update.message.animation:
            bot_data['cabecalho_media_id'] = update.message.animation.file_id
            bot_data['cabecalho_media_type'] = 'animation'
            await update.message.reply_text("GIF do cabeçalho atualizado com sucesso!")
            save_data()
        elif update.message.video:
            bot_data['cabecalho_media_id'] = update.message.video.file_id
            bot_data['cabecalho_media_type'] = 'video'
            await update.message.reply_text("Vídeo do cabeçalho atualizado com sucesso!")
            save_data()
        else:
            await update.message.reply_text("Por favor, envie uma foto, GIF ou vídeo para o cabeçalho.")
            return # Não limpa o estado se a mídia não for válida
        context.user_data.pop('estado')
    elif user_chat_id == ADMIN_CHAT_ID: # Mídia enviada pelo admin, mas não no estado correto
         await update.message.reply_text("Por favor, use o comando /editar_cabecalho primeiro para iniciar a edição do cabeçalho.")
    else: # Mídia enviada por outro usuário, não é um comando ou estado esperado
        await update.message.reply_text("Desculpe, não entendi o que você quis dizer. Use /ajuda para ver os comandos disponíveis.")


async def new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lida com a adição de novos membros ao chat, incluindo o próprio bot."""
    logger.debug(f"DEBUG: >>> FUNÇÃO new_chat_members FOI ACIONADA <<<")
    
    if not update.message: 
        logger.warning("DEBUG: new_chat_members chamada sem update.message. Ignorando.")
        return

    chat_id = update.message.chat_id
    chat_title = update.message.chat.title if update.message.chat.title else f"Chat ID {chat_id}"
    chat_type = update.message.chat.type
    bot_member = await context.bot.get_me()
    logger.debug(f"DEBUG: Chat ID: {chat_id}, Título: '{chat_title}', Tipo: '{chat_type}', ID do Bot: {bot_member.id}")

    # Itera sobre os novos membros adicionados
    for member in update.message.new_chat_members:
        logger.debug(f"DEBUG: Membro adicionado: {member.full_name} (ID: {member.id}), é bot: {member.is_bot}")

        # Se o membro adicionado for o próprio bot
        if member.id == bot_member.id:
            logger.debug(f"DEBUG: O bot foi identificado como o membro adicionado.")

            try:
                # Obtém o status do bot no chat para verificar permissões
                chat_member_status = await context.bot.get_chat_member(chat_id, bot_member.id)
                
                is_admin_in_chat = chat_member_status.status == ChatMember.ADMINISTRATOR
                has_post_messages_perm = chat_member_status.can_post_messages if chat_member_status.can_post_messages is not None else False
                
                logger.debug(f"DEBUG: Status do Bot em '{chat_title}': Admin: {is_admin_in_chat}, Pode Postar Mensagens: {has_post_messages_perm}")

                # Condição de Permissão: O bot DEVE ser administrador e ter permissão para postar mensagens.
                if is_admin_in_chat and has_post_messages_perm:
                    logger.info(f"INFO: Bot tem permissões adequadas em '{chat_title}' (ID: {chat_id}). Prosseguindo com o cadastro.")

                    invite_link = context.user_data.pop('cadastrando_link', "Link não encontrado ou privado")
                    user_id_solicitante = context.user_data.pop('user_id_cadastro', None) # Pega o ID do solicitante
                    
                    try:
                        # Tenta obter o link de convite (só funciona se o bot for admin e tiver permissão)
                        if chat_type in ['channel', 'supergroup']:
                            new_invite_link = await context.bot.export_chat_invite_link(chat_id)
                            logger.debug(f"DEBUG: Novo link de convite obtido: {new_invite_link}")
                            # Prioriza o link obtido pelo bot se for diferente do que o usuário enviou
                            if new_invite_link and "t.me/" in new_invite_link:
                                invite_link = new_invite_link
                        else:
                             logger.debug("DEBUG: Tipo de chat não suporta export_chat_invite_link ou não é relevante.")
                    except Exception as e:
                        logger.warning(f"AVISO: Erro ao obter link de convite para {chat_id}: {e}")

                    num_members = 0
                    try:
                        # Tenta obter o número de membros (approximate_member_count está em Chat)
                        chat_info = await context.bot.get_chat(chat_id)
                        num_members = chat_info.approximate_member_count if chat_info.approximate_member_count is not None else 0
                        logger.debug(f"DEBUG: Número aproximado de membros: {num_members}")
                    except Exception as e:
                        logger.warning(f"AVISO: Não foi possível obter o número de membros para {chat_id}: {e}")

                    # REGRA DE 50 MEMBROS (Aplicada apenas se não for um chat privado)
                    if chat_type != 'private' and num_members < 50:
                        logger.info(f"INFO: Canal/grupo '{chat_title}' (ID: {chat_id}) com {num_members} membros. Ignorado por ter menos de 50 membros.")
                        try:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=f"Olá! Eu sou o bot de divulgação. Seu canal/grupo '{chat_title}' tem apenas {num_members} membros. "
                                "Não o adicionarei à lista de divulgação por ter menos de 50 membros. Por favor, me remova do canal."
                            )
                        except Exception as e:
                            logger.error(f"Erro ao enviar mensagem de aviso de membros insuficientes para {chat_id}: {e}")
                        
                        # Notifica o usuário que solicitou o cadastro, se soubermos quem é
                        if user_id_solicitante:
                             try:
                                 await context.bot.send_message(
                                     chat_id=user_id_solicitante,
                                     text=f"⚠️ O cadastro do seu canal/grupo **{chat_title}** (`{chat_id}`) falhou. Ele tem apenas **{num_members}** membros, e o mínimo exigido é 50. Por favor, remova o bot do seu canal/grupo e tente novamente quando tiver mais membros.",
                                     parse_mode='Markdown'
                                 )
                             except Exception as e:
                                 logger.error(f"Erro ao enviar notificação de falha por membros insuficientes para o solicitante {user_id_solicitante}: {e}")
                        
                        # Opcional: fazer o bot sair se a regra não for atendida (descomente se quiser)
                        # if chat_type in ['group', 'supergroup', 'channel']:
                        #     await context.bot.leave_chat(chat_id)
                        return # Sai da função, não cadastra o chat

                    # Se passou em todas as verificações, cadastra o canal/grupo
                    logger.info(f"INFO: Cadastrando canal/grupo: '{chat_title}' (ID: {chat_id}) com {num_members} membros.")
                    bot_data['canais_e_grupos'][chat_id] = { # Armazena como str, pois chaves de JSON são strings
                        'nome': chat_title,
                        'tipo': chat_type,
                        'link': invite_link,
                        'membros': num_members
                    }
                    save_data()
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"Obrigado por me adicionar! Canal/Grupo '{chat_title}' ({chat_id}) foi adicionado à lista de divulgação com {num_members} membros."
                        )
                    except Exception as e:
                        logger.error(f"Erro ao enviar mensagem de sucesso de cadastro para {chat_id}: {e}")
                    
                    # Envia notificação ao usuário que solicitou o cadastro (se for diferente do chat_id)
                    if user_id_solicitante and user_id_solicitante != chat_id:
                        try:
                            await context.bot.send_message(
                                chat_id=user_id_solicitante,
                                text=f"✅ Seu canal/grupo **{chat_title}** (`{chat_id}`) foi cadastrado com sucesso! Ele já está na nossa lista de divulgação. Você pode conferir a lista completa usando o comando /ver_canais (se você for o admin) ou aguardar a próxima publicação."
                                , parse_mode='Markdown'
                            )
                        except Exception as e:
                            logger.error(f"Erro ao enviar notificação de sucesso ao solicitante {user_id_solicitante}: {e}")

                    # Envia notificação ao ADMIN_CHAT_ID
                    if ADMIN_CHAT_ID:
                        try:
                            await context.bot.send_message(
                                chat_id=ADMIN_CHAT_ID,
                                text=f"Novo canal/grupo cadastrado: **{chat_title}** (`{chat_id}`) com **{num_members}** membros. Link: {invite_link}",
                                parse_mode='Markdown'
                            )
                        except Exception as e:
                            logger.error(f"Erro ao enviar notificação de novo canal ao admin: {e}")
                else:
                    # O bot não tem as permissões necessárias
                    error_message = f"Olá! Fui adicionado ao '{chat_title}', mas preciso ser **administrador** com permissões para **'Postar mensagens'** para funcionar corretamente."
                    if not is_admin_in_chat:
                        error_message += "\n- Por favor, me torne administrador."
                    if not has_post_messages_perm:
                        error_message += "\n- Por favor, me dê permissão para 'Postar mensagens'."
                    error_message += "\nPor favor, me remova do canal/grupo e adicione-me novamente com as permissões corretas para que eu possa cadastrá-lo."
                    
                    logger.warning(f"AVISO: Bot adicionado sem permissões suficientes em '{chat_title}' (ID: {chat_id}). Mensagem enviada ao chat: '{error_message}'")
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=error_message
                        )
                    except Exception as e:
                        logger.error(f"Erro ao enviar mensagem de erro de permissão para {chat_id}: {e}")
                    
                    # Notifica o usuário que solicitou o cadastro, se soubermos quem é
                    user_id_solicitante = context.user_data.pop('user_id_cadastro', None)
                    if user_id_solicitante and user_id_solicitante != chat_id:
                         try:
                             await context.bot.send_message(
                                 chat_id=user_id_solicitante,
                                 text=f"⚠️ O cadastro do seu canal/grupo **{chat_title}** (`{chat_id}`) falhou. Não tenho as permissões necessárias. Por favor, remova o bot e adicione-o novamente garantindo as permissões de administrador (Postar mensagens e Adicionar membros).",
                                 parse_mode='Markdown'
                             )
                         except Exception as e:
                             logger.error(f"Erro ao enviar notificação de falha por permissão para o solicitante {user_id_solicitante}: {e}")

                    # Notifica o ADMIN_CHAT_ID sobre o problema de permissão
                    if ADMIN_CHAT_ID:
                        try:
                            await context.bot.send_message(
                                chat_id=ADMIN_CHAT_ID,
                                text=f"**AVISO:** Fui adicionado ao canal/grupo **{chat_title}** (`{chat_id}`) mas não tenho as permissões de administrador necessárias. Não pude cadastrá-lo."
                            )
                        except Exception as admin_send_e:
                            logger.error(f"Erro ao enviar aviso de permissão ao admin: {admin_send_e}")

            except Exception as e:
                # Captura e loga qualquer erro inesperado durante o processo
                logger.critical(
                    f"ERRO CRÍTICO INESPERADO no new_chat_members para {chat_id}: {e}", exc_info=True)
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="Ocorreu um erro interno ao tentar verificar minhas permissões ou cadastrar o chat. Por favor, contate o administrador do bot."
                    )
                except Exception as send_e:
                    logger.error(f"Erro ao enviar mensagem de erro crítico para {chat_id}: {send_e}")
                
                user_id_solicitante = context.user_data.pop('user_id_cadastro', None)
                if user_id_solicitante and user_id_solicitante != chat_id:
                     try:
                         await context.bot.send_message(
                             chat_id=user_id_solicitante,
                             text=f"❌ Ocorreu um erro inesperado ao tentar cadastrar seu canal/grupo **{chat_title}** (`{chat_id}`). Por favor, contate o administrador do bot."
                         , parse_mode='Markdown')
                     except Exception as e:
                         logger.error(f"Erro ao enviar notificação de erro inesperado ao solicitante {user_id_solicitante}: {e}")

                if ADMIN_CHAT_ID:
                    try:
                        await context.bot.send_message(
                            chat_id=ADMIN_CHAT_ID,
                            text=f"**ERRO CRÍTICO:** Ocorreu um erro inesperado no `new_chat_members` ao processar a adição do bot ao chat **{chat_title}** (`{chat_id}`). Erro: `{e}`"
                        )
                    except Exception as admin_send_e:
                        logger.error(f"Erro ao enviar erro crítico ao admin: {admin_send_e}")
            
            # Limpa o estado de aguardando_link_cadastro e o user_id_cadastro SOMENTE APÓS O PROCESSAMENTO DO BOT
            if 'estado' in context.user_data and context.user_data['estado'] == 'aguardando_link_cadastro':
                context.user_data.pop('estado')
            if 'cadastrando_link' in context.user_data:
                context.user_data.pop('cadastrando_link')
            if 'user_id_cadastro' in context.user_data:
                context.user_data.pop('user_id_cadastro')

            return # Processamos a adição do bot, então saímos do loop de membros.

    logger.debug("DEBUG: O bot não foi o membro adicionado ou nenhum bot foi adicionado neste evento.")


async def left_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lida com a saída de membros do chat, incluindo o próprio bot."""
    logger.debug(f"DEBUG: left_chat_member acionada. Chat ID: {update.message.chat_id}, Título: '{update.message.chat.title}'")
    
    if not update.message: # Verificação de segurança
        logger.warning("left_chat_member chamada sem update.message. Ignorando.")
        return

    bot_member = await context.bot.get_me()
    chat_id = update.message.chat_id # ID como int
    chat_title = update.message.chat.title

    # Verifica cada membro que saiu
    for member in update.message.left_chat_member:
        logger.debug(f"DEBUG: Membro que saiu: {member.full_name} (ID: {member.id}), é bot: {member.is_bot}")

        # Se o membro que saiu for o próprio bot
        if member.id == bot_member.id:
            logger.info(f"INFO: O bot foi removido do chat '{chat_title}' ({chat_id}).")

            if chat_id in bot_data.get('canais_e_grupos', {}):
                del bot_data['canais_e_grupos'][chat_id]
                save_data()
                logger.info(f"INFO: Canal/grupo '{chat_title}' ({chat_id}) removido da lista de divulgação.")
                if ADMIN_CHAT_ID:
                    try:
                        await context.bot.send_message(
                            chat_id=ADMIN_CHAT_ID,
                            text=f"**AVISO:** O bot foi removido do canal/grupo **{chat_title}** (`{chat_id}`). Ele foi removido da lista de divulgação.",
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"Erro ao enviar aviso de remoção de chat ao admin: {e}")
            else:
                logger.info(f"INFO: Bot saiu de um chat não cadastrado: '{chat_title}' ({chat_id}).")
                if ADMIN_CHAT_ID:
                    try:
                        await context.bot.send_message(
                            chat_id=ADMIN_CHAT_ID,
                            text=f"**INFO:** O bot foi removido de um canal/grupo **não cadastrado**: **{chat_title}** (`{chat_id}`).",
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"Erro ao enviar aviso de saída de chat não cadastrado ao admin: {e}")
            return # Já tratamos a saída do bot, não precisamos verificar outros membros.
    logger.debug("DEBUG: Um membro saiu, mas não foi o bot.")


# --- Função Main (Início do Bot e Registro de Handlers) ---
def main() -> None:
    """Inicia o bot."""
    # Carrega os dados persistentes no início
    load_data()

    # Inicia o servidor Flask em uma thread separada para keep-alive (para Render.com)
    keep_alive()

    # Cria o Application e passa o token do bot
    application = Application.builder().token(BOT_TOKEN).build()

    # Se já houver um ADMIN_CHAT_ID, tente agendar os jobs no startup.
    # Usar job_queue.run_once para chamar a função assíncrona.
    if ADMIN_CHAT_ID:
        # job_queue.run_once executa a corrotina no loop de eventos do PTB
        application.job_queue.run_once(agendar_daily_jobs_on_startup, 0)
        logger.info(f"ADMIN_CHAT_ID carregado no bot: {ADMIN_CHAT_ID}. Tentando agendar jobs.")
    else:
        logger.info("ADMIN_CHAT_ID não definido. Aguardando o comando /start do administrador.")


    # --- REGISTRO DE TODOS OS HANDLERS ---
    # CommandHandlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cadastrar", cadastrar))
    application.add_handler(CommandHandler("ver_canais", ver_canais_e_grupos))
    application.add_handler(CommandHandler("editar_cabecalho", editar_cabecalho)) # Novo comando
    application.add_handler(CommandHandler("agendar", agendar))
    application.add_handler(CommandHandler("parar_agendamento", parar_agendamento))
    application.add_handler(CommandHandler("retomar_agendamento", retomar_agendamento))
    application.add_handler(CommandHandler("testar_envio", testar_envio))
    application.add_handler(CommandHandler("ajuda", ajuda))
    application.add_handler(CommandHandler("remover_canal", remover_canal))
    application.add_handler(CommandHandler("cancelar", cancelar)) # Importante para sair de estados

    # MessageHandlers (para texto, mídia e atualizações de status)
    # Importante: o filters.COMMAND deve vir antes do filters.TEXT
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_response))
    application.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO | filters.ANIMATION), handle_media_cabecalho))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_members))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, left_chat_member))

    # CallbackQueryHandler (para botões inline)
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Inicia o polling do bot
    logger.info("Bot Telegram iniciando polling...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.critical(f"Erro crítico ao iniciar o polling do bot: {e}", exc_info=True)


if __name__ == "__main__":
    # Garante que a função main seja executada apenas quando o script é o principal.
    main()