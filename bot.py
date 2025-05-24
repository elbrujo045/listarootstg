import os
import asyncio
import logging
import datetime
import json
import random
from datetime import timedelta
import pytz # Importa a biblioteca pytz para lidar com fusos horários

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest, Forbidden

from flask import Flask
from threading import Thread

# --- Configuração de Log ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG # MANTENHA COMO DEBUG para depuração completa
)
logger = logging.getLogger(__name__)

# --- Variáveis Globais (Carregadas ou Definidas) ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "SEU_TOKEN_DO_BOT_AQUI")
if BOT_TOKEN == "SEU_TOKEN_DO_BOT_AQUI":
    logger.critical("ATENÇÃO: BOT_TOKEN não configurado! Por favor, defina a variável de ambiente BOT_TOKEN.")

bot_data = {} # Dicionário para armazenar dados persistentes
DATA_FILE = 'bot_data.json' # Arquivo para persistir os dados

ADMIN_CHAT_ID = None # Será definido pelo comando /start pelo primeiro usuário

# Define o fuso horário para o agendamento.
# É CRUCIAL que você defina o fuso horário correto para a sua região.
# Ex: 'America/Sao_Paulo' para horário de Brasília.
# Para ver a lista completa de fusos horários válidos, pesquise por "List of tz database time zones"
TIMEZONE = pytz.timezone('America/Sao_Paulo') # ALtere se sua região for diferente

# --- Funções de Persistência de Dados ---
def load_data():
    global bot_data, ADMIN_CHAT_ID
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            loaded_data = json.load(f)
            # Converte chaves de volta para int se necessário (chat_ids são strings para chaves de JSON)
            bot_data['canais_e_grupos'] = {int(k): v for k, v in loaded_data.get('canais_e_grupos', {}).items()}
            bot_data['agendamentos'] = {int(k): v for k, v in loaded_data.get('agendamentos', {}).items()}
            bot_data['cabecalho_texto'] = loaded_data.get('cabecalho_texto', "✨ **Confira essas listas de canais e grupos no Telegram!** ✨")
            bot_data['cabecalho_media_id'] = loaded_data.get('cabecalho_media_id', None)
            bot_data['cabecalho_media_type'] = loaded_data.get('cabecalho_media_type', None)
            ADMIN_CHAT_ID = loaded_data.get('ADMIN_CHAT_ID') # Carrega ADMIN_CHAT_ID persistente
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
    data_to_save['ADMIN_CHAT_ID'] = ADMIN_CHAT_ID # Salva o ADMIN_CHAT_ID global

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
            canais_para_remover.append(chat_id_int)
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
    logger.info("Iniciando agendamento de jobs diários na inicialização.")
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
        logger.info(f"Job existente 'daily_post_job' removido: {job.next_run_time}")

    if not ativo or not horarios_str:
        logger.info("Agendamento desativado ou sem horários definidos para o admin. Nenhum job será agendado.")
        if ADMIN_CHAT_ID and ADMIN_CHAT_ID in bot_data['agendamentos'] and bot_data['agendamentos'][ADMIN_CHAT_ID].get('ativo'):
             try:
                 await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="Agendamento desativado ou sem horários. Jobs anteriores removidos.")
             except Exception as e:
                 logger.error(f"Erro ao enviar mensagem de desativação de agendamento ao admin: {e}")
        return

    agendados_com_sucesso = []
    for horario_str in horarios_str:
        try:
            # Converte o horário para um objeto time aware do fuso horário definido
            h_naive = datetime.time.fromisoformat(horario_str)
            # Combina com uma data mínima e localiza no fuso horário para obter um datetime aware
            # Em seguida, extrai apenas a parte do tempo aware para usar com run_daily
            h_aware = TIMEZONE.localize(datetime.datetime.combine(datetime.date.min, h_naive)).time()

            job = context.job_queue.run_daily(
                send_daily_posts,
                time=h_aware, # Usa o objeto time com fuso horário
                days=tuple(range(7)),  # Todos os dias da semana
                data={'admin_id': ADMIN_CHAT_ID},
                name="daily_post_job"
            )
            # Calcula a próxima execução no fuso horário *definido* para o feedback
            # job.next_run_time já está em UTC. Convertemos para o fuso horário que o usuário configurou para exibição.
            next_run_display = job.next_run_time.astimezone(TIMEZONE).strftime('%d/%m %H:%M')
            agendados_com_sucesso.append(f"• {horario_str} (próxima execução: {next_run_display})")
            logger.info(f"Job 'daily_post_job' agendado para {horario_str} ({TIMEZONE.tzname(datetime.datetime.now())}). Próxima execução (UTC): {job.next_run_time}")
        except ValueError:
            logger.error(f"Horário inválido '{horario_str}' no agendamento. Ignorando.")
        except Exception as e:
            logger.error(f"Erro inesperado ao agendar para '{horario_str}': {e}", exc_info=True)

    if agendados_com_sucesso and ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text="✅ **Agendamentos de posts diários ativos:**\n" + "\n".join(agendados_com_sucesso) + f"\n\n*(Horários em {TIMEZONE.tzname(datetime.datetime.now())})*",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Erro ao enviar confirmação de agendamento ao admin: {e}")
    elif ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text="❌ **Nenhum agendamento diário válido foi configurado ou ativado.** Use /agendar para definir horários."
            )
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem de nenhum agendamento ao admin: {e}")


# --- Handlers de Comandos ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia uma mensagem de boas-vindas e define o ADMIN_CHAT_ID se for o primeiro."""
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    user_name = update.message.from_user.first_name

    global ADMIN_CHAT_ID # Indica que estamos modificando a variável global

    if ADMIN_CHAT_ID is None:
        ADMIN_CHAT_ID = chat_id
        # bot_data['ADMIN_CHAT_ID'] = chat_id # Já está sendo salvo na função save_data() via global
        save_data() # Salva imediatamente o ADMIN_CHAT_ID para persistência
        logger.info(f"ADMIN_CHAT_ID definido como {chat_id} por {user_name}.")
        await update.message.reply_text(
            f"Olá, {user_name}! Você foi definido como o administrador deste bot.\n\n"
            "Use /ajuda para ver os comandos disponíveis."
        )
        # Tenta agendar jobs se já houver horários configurados para o novo admin
        # CHAMADA AQUI É CRUCIAL PARA INICIALIZAR JOBS SE HOUVER ADMIN
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
        f"*(Horário de referência: {TIMEZONE.tzname(datetime.datetime.now())})*\n" # Informa o fuso horário
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
        keyboard.append([InlineKeyboardButton("Editar Cabeçalho", callback_data="admin_editar_cabecalho")])
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
        logger.debug(f"DEBUG: Cancelando operação, estado '{context.user_data.get('estado')}' de {message.chat.id}")
        context.user_data.pop('estado', None) # Remove de forma segura
        context.user_data.pop('user_id_cadastro', None) # Remove o user_id_cadastro
        context.user_data.pop('cadastrando_link', None) # Remove o link de cadastro
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
    # Permite que não-admins cliquem em botões de remoção que o admin gerou
    if query.message.chat.id != ADMIN_CHAT_ID and not query.data.startswith('remove_chat_'):
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
    
    elif query.data == 'admin_editar_cabecalho':
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
                    "O link parece inválido. Por favor, envie um link de convite válido que comece com `https://t.me/` ou `https://t.me/+`.\n"
                    "Envie /cancelar para abortar."
                    , parse_mode='Markdown'
                )
                return

            context.user_data['cadastrando_link'] = link
            # Remove o estado temporário aguardando_link_cadastro
            context.user_data.pop('estado', None)

            # Pede para adicionar o bot ao canal/grupo
            keyboard = [[InlineKeyboardButton("Adicionar Bot ao Canal/Grupo", url="https://t.me/SEU_BOT_USERNAME?startgroup=true")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Pede confirmação
            await update.message.reply_text(
                "✅ Link recebido! Agora, por favor, adicione este bot ao seu canal ou grupo como **administrador** (com permissão para enviar mensagens).\n\n"
                "Após adicionar o bot, clique em 'Verificar Adesão' para que eu possa confirmar.\n"
                "Envie /cancelar para abortar."
                , reply_markup=reply_markup
                , parse_mode='Markdown'
            )
            # Define o próximo estado para aguardar a adição do bot
            context.user_data['estado'] = 'aguardando_adesao_bot'
            save_data() # Salva o estado para persistência se o bot reiniciar


        else:
            await update.message.reply_text(
                "Parece que não é um link de convite válido do Telegram. Por favor, envie um link que contenha `t.me/` ou `telegram.me/`.\n"
                "Envie /cancelar para abortar."
            )
            return

    # Lida com o estado de agendamento (apenas para o admin)
    elif current_state == 'aguardando_horarios_agendamento' and user_chat_id == ADMIN_CHAT_ID:
        horarios_input = update.message.text.strip()
        horarios_list = [h.strip() for h in horarios_input.split(',')]
        valid_horarios = []
        invalid_horarios = []

        for h in horarios_list:
            try:
                datetime.time.fromisoformat(h) # Tenta converter para validar o formato HH:MM
                valid_horarios.append(h)
            except ValueError:
                invalid_horarios.append(h)

        if valid_horarios:
            bot_data.setdefault('agendamentos', {})
            # Garante que ADMIN_CHAT_ID é um int para ser a chave
            bot_data['agendamentos'][ADMIN_CHAT_ID] = {
                'horarios': valid_horarios,
                'ativo': True
            }
            save_data()
            context.user_data.pop('estado', None) # Limpa o estado
            
            await update.message.reply_text(
                f"✅ Horários salvos e agendamento ativado!\n"
                f"Horários agendados: {', '.join(valid_horarios)}\n"
                f"Os posts serão enviados diariamente nesses horários (Fuso: {TIMEZONE.tzname(datetime.datetime.now())})."
            )
            await agendar_daily_jobs_on_startup(context) # Re-agenda os jobs com os novos horários
        else:
            await update.message.reply_text(
                "Nenhum horário válido foi fornecido. Por favor, use o formato HH:MM (ex: `09:00, 15:30`).\n"
                f"Horários inválidos ignorados: {', '.join(invalid_horarios)}\n"
                "Envie /cancelar para abortar."
            )
    
    # Lida com a edição de texto do cabeçalho (apenas para o admin)
    elif current_state == 'aguardando_texto_cabecalho_fluxo' and user_chat_id == ADMIN_CHAT_ID:
        new_text = update.message.text
        bot_data['cabecalho_texto'] = new_text
        save_data()
        context.user_data.pop('estado', None)
        await update.message.reply_text(
            f"✅ Texto do cabeçalho atualizado com sucesso!\n\nPreview:\n{new_text}"
            , parse_mode='Markdown'
        )
        logger.info(f"Texto do cabeçalho atualizado pelo admin {ADMIN_CHAT_ID}.")

    # Lida com respostas que não correspondem a nenhum estado conhecido
    else:
        # Se não há estado, é uma mensagem normal.
        # Ou se o estado não é esperado para o tipo de mensagem.
        # Você pode adicionar um tratamento para mensagens desconhecidas aqui.
        logger.debug(f"Mensagem de texto não tratada: {update.message.text} de {update.message.chat_id}")
        # await update.message.reply_text("Desculpe, não entendi. Use /ajuda para ver os comandos.")


async def handle_media_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lida com o recebimento de mídia para o cabeçalho."""
    user_chat_id = update.message.chat_id
    current_state = context.user_data.get('estado')

    if current_state == 'aguardando_media_cabecalho_fluxo' and user_chat_id == ADMIN_CHAT_ID:
        media_id = None
        media_type = None

        if update.message.photo:
            media_id = update.message.photo[-1].file_id # Pega a maior resolução
            media_type = 'photo'
        elif update.message.video:
            media_id = update.message.video.file_id
            media_type = 'video'
        elif update.message.animation: # Para GIFs
            media_id = update.message.animation.file_id
            media_type = 'animation'
        
        if media_id and media_type:
            bot_data['cabecalho_media_id'] = media_id
            bot_data['cabecalho_media_type'] = media_type
            save_data()
            context.user_data.pop('estado', None)
            await update.message.reply_text(f"✅ Mídia do cabeçalho ({media_type}) atualizada com sucesso!")
            logger.info(f"Mídia do cabeçalho ({media_type}) atualizada pelo admin {ADMIN_CHAT_ID}.")
        else:
            await update.message.reply_text("Por favor, envie uma foto, GIF ou vídeo válido para o cabeçalho. Outros tipos de mídia não são suportados para o cabeçalho.")
    else:
        logger.debug(f"Mídia não tratada: {update.message} de {update.message.chat_id} (Estado: {current_state})")


async def handle_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verifica se o bot foi adicionado a um canal/grupo para cadastro."""
    bot_member = None
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            bot_member = member
            break

    if bot_member:
        chat_id_joined = update.message.chat_id
        chat_name = update.message.chat.title
        chat_type = update.message.chat.type # 'group', 'supergroup', 'channel'

        # Verifica se é um grupo ou canal (supergroup)
        if chat_type in ['group', 'supergroup', 'channel']:
            # Verifique se o bot está no estado 'aguardando_adesao_bot' e se o user_id_cadastro é o admin
            # Ou, de forma mais geral, se o ADMIN_CHAT_ID está realizando o cadastro
            user_id_requesting_cadastro = context.user_data.get('user_id_cadastro')
            cadastrando_link = context.user_data.get('cadastrando_link')

            # Tenta obter informações do chat para validar o link
            chat_info = None
            try:
                # Obter o chat completo para verificar link de convite primário
                chat_info = await context.bot.get_chat(chat_id_joined)
                logger.debug(f"Chat info: {chat_info}")
            except Exception as e:
                logger.error(f"Erro ao obter informações do chat {chat_id_joined}: {e}")
                # Se não conseguir info, não pode cadastrar
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"❌ Erro ao tentar obter informações do chat `{chat_name}` (`{chat_id_joined}`). Não foi possível cadastrar."
                    , parse_mode='Markdown'
                )
                return

            # Validação: Checar se o bot tem permissão de postar.
            # Em canais, ele precisa ser admin para enviar mensagens.
            # Em grupos, também.
            try:
                bot_status = await context.bot.get_chat_member(chat_id_joined, context.bot.id)
                if not bot_status.can_post_messages: # Verifica a permissão 'post_messages' para canais/grupos
                    await context.bot.send_message(
                        chat_id=user_id_requesting_cadastro if user_id_requesting_cadastro else ADMIN_CHAT_ID,
                        text=f"⚠️ Fui adicionado ao **{chat_name}**, mas não tenho permissão para enviar mensagens. Por favor, me dê essa permissão para que eu possa divulgar o canal/grupo."
                        , parse_mode='Markdown'
                    )
                    logger.warning(f"Bot adicionado a {chat_name} ({chat_id_joined}) mas sem permissão de postagem.")
                    return
            except Exception as e:
                logger.error(f"Erro ao verificar permissões do bot no chat {chat_id_joined}: {e}")
                await context.bot.send_message(
                    chat_id=user_id_requesting_cadastro if user_id_requesting_cadastro else ADMIN_CHAT_ID,
                    text=f"❌ Erro ao verificar minhas permissões no chat `{chat_name}` (`{chat_id_joined}`). Por favor, verifique manualmente se tenho permissão para enviar mensagens."
                    , parse_mode='Markdown'
                )
                return
            
            # Tentar obter o link de convite primário do chat, se disponível
            # Este link é mais confiável do que o link fornecido pelo usuário.
            # Para canais, bot.invite_link pode ser o link de convite principal se o bot for admin.
            # Para grupos, é o link de convite, se tiver.
            actual_invite_link = chat_info.invite_link if chat_info.invite_link else cadastrando_link
            
            if not actual_invite_link:
                await context.bot.send_message(
                    chat_id=user_id_requesting_cadastro if user_id_requesting_cadastro else ADMIN_CHAT_ID,
                    text=f"❌ Não consegui obter o link de convite para **{chat_name}** (`{chat_id_joined}`). Não foi possível cadastrar. Por favor, certifique-se de que o bot tem permissão para gerenciar links de convite ou que você forneceu um link válido via /cadastrar."
                    , parse_mode='Markdown'
                )
                logger.warning(f"Não foi possível obter o link de convite para {chat_name} ({chat_id_joined}).")
                return

            bot_data.setdefault('canais_e_grupos', {})
            bot_data['canais_e_grupos'][chat_id_joined] = {
                'nome': chat_name,
                'tipo': chat_type,
                'link': actual_invite_link,
                'data_cadastro': datetime.datetime.now(TIMEZONE).isoformat() # Data de cadastro no fuso horário
            }
            save_data()

            # Limpa o estado após o cadastro bem-sucedido
            context.user_data.pop('estado', None)
            context.user_data.pop('user_id_cadastro', None)
            context.user_data.pop('cadastrando_link', None)

            response_message = (
                f"✅ **{chat_name}** foi cadastrado(a) com sucesso!\n"
                f"Tipo: `{chat_type}`\n"
                f"Link de convite: {actual_invite_link}\n\n"
                "A partir de agora, este canal/grupo será incluído nas divulgações diárias."
            )
            
            # Envia a confirmação para o usuário que pediu o cadastro (se houver)
            if user_id_requesting_cadastro:
                await context.bot.send_message(
                    chat_id=user_id_requesting_cadastro,
                    text=response_message,
                    parse_mode='Markdown'
                )
            
            # Envia também para o admin, se for diferente do usuário que pediu
            if ADMIN_CHAT_ID and (not user_id_requesting_cadastro or user_id_requesting_cadastro != ADMIN_CHAT_ID):
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"🔔 **Notificação de Cadastro:**\n" + response_message,
                    parse_mode='Markdown'
                )
            logger.info(f"Canal/grupo '{chat_name}' ({chat_id_joined}) cadastrado com sucesso.")

        else:
            logger.warning(f"Bot adicionado a um chat que não é grupo/supergrupo/canal: {chat_name} ({chat_id_joined}) Tipo: {chat_type}")
            if ADMIN_CHAT_ID:
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=f"⚠️ Fui adicionado a um chat de tipo `{chat_type}` (não é grupo ou canal) `{chat_name}` (`{chat_id_joined}`). Não foi possível cadastrar."
                        , parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Erro ao notificar admin sobre tipo de chat inválido: {e}")

async def handle_left_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lida com a remoção de membros do chat."""
    # Se o bot foi removido de um grupo/canal
    if update.message.left_chat_member.id == context.bot.id:
        chat_id_left = update.message.chat_id
        if chat_id_left in bot_data.get('canais_e_grupos', {}):
            removed_name = bot_data['canais_e_grupos'][chat_id_left]['nome']
            del bot_data['canais_e_grupos'][chat_id_left]
            save_data()
            logger.info(f"Bot foi removido do chat '{removed_name}' ({chat_id_left}). Removido da lista de divulgação.")
            if ADMIN_CHAT_ID:
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=f"⚠️ **ATENÇÃO:** Fui removido(a) do canal/grupo **'{removed_name}'** (`{chat_id_left}`). Ele(a) foi automaticamente removido(a) da sua lista de divulgação."
                        , parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Erro ao notificar admin sobre saída do chat: {e}")

# --- Função Main e Execução do Bot ---
async def main() -> None:
    """Inicia o bot e o loop de eventos."""
    load_data() # Carrega os dados antes de iniciar o aplicativo

    application = Application.builder().token(BOT_TOKEN).build()

    # Adiciona os handlers de comandos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cadastrar", cadastrar))
    application.add_handler(CommandHandler("ajuda", ajuda))
    application.add_handler(CommandHandler("cancelar", cancelar))
    application.add_handler(CommandHandler("vercanais", ver_canais_e_grupos))
    application.add_handler(CommandHandler("editarcabecalho", editar_cabecalho))
    application.add_handler(CommandHandler("agendar", agendar))
    application.add_handler(CommandHandler("pararagendamento", parar_agendamento))
    application.add_handler(CommandHandler("retomaragendamento", retomar_agendamento))
    application.add_handler(CommandHandler("testarenvio", testar_envio))
    application.add_handler(CommandHandler("removercanal", remover_canal))

    # Adiciona handlers para mensagens de texto, mídia, e membros de chat
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_response))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION, handle_media_response))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_chat_members))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, handle_left_chat_member))

    # Adiciona handler para callbacks de botões inline
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Inicia o servidor Flask em uma thread separada para o Keep-Alive
    keep_alive()

    # Agenda os jobs diários na inicialização (se ADMIN_CHAT_ID já estiver definido)
    # Deve ser feito APÓS o build da application e antes de start_polling
    application.job_queue.run_once(agendar_daily_jobs_on_startup, 1) # Roda 1 segundo após o app iniciar

    logger.info("Bot iniciando polling...")
    await application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        # AQUI MANTEMOS A CHAMADA SIMPLES, CONFIANDO QUE O REPLIT (ou Render)
        # lidará com o loop de eventos sem conflito.
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Erro crítico no loop principal do bot: {e}", exc_info=True)
        