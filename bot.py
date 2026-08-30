import logging
import os
import sys
from datetime import datetime, timedelta
import random
import requests
import json
import threading
import time
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# =============================================
# CARGA DE VARIABLES DE ENTORNO (.env)
# =============================================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("❌ ERROR: BOT_TOKEN no encontrado en .env")
    sys.exit(1)

try:
    ADMINISTRADOR_ID = int(os.getenv("ADMINISTRADOR_ID", 0))
    if ADMINISTRADOR_ID == 0:
        print("⚠️ ADMINISTRADOR_ID no configurado, usa el valor por defecto")
except ValueError:
    print("⚠️ ADMINISTRADOR_ID inválido, usa el valor por defecto")
    ADMINISTRADOR_ID = 123456789

COMANDO_PANEL = os.getenv("COMANDO_PANEL", "admin")

# =============================================
# CONFIGURACIÓN DE LOGGING
# =============================================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('nexus_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

logger.info("🚀 Iniciando Nexus Crypto Bot...")

# =============================================
# BASE DE DATOS (SQLITE)
# =============================================

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session

engine = create_engine("sqlite:///nexus_crypto_bot.db", connect_args={"check_same_thread": False})
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()

# =============================================
# MODELOS DE BASE DE DATOS
# =============================================

class UsuarioDB(Base):
    __tablename__ = "usuarios"
    
    telegram_id = Column(Integer, primary_key=True)
    username = Column(String(100), default="")
    idioma = Column(String(10), default="es")
    balance_general = Column(JSON, default={})
    balance_venta = Column(JSON, default={})
    balance_intercambio = Column(JSON, default={})
    balance_apuestas = Column(JSON, default={})
    balance_retiro = Column(JSON, default={})
    balance_cuc = Column(Float, default=0.0)
    reputacion = Column(Float, default=5.0)
    operaciones = Column(Integer, default=0)
    premium = Column(Boolean, default=False)
    tipo_premium = Column(String(20), nullable=True)
    fecha_premium = Column(DateTime, nullable=True)
    fecha_registro = Column(DateTime, default=datetime.now)
    ultima_actividad = Column(DateTime, default=datetime.now)
    baneado = Column(Boolean, default=False)

class TransaccionDB(Base):
    __tablename__ = "transacciones"
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer)
    tipo = Column(String(50))
    moneda = Column(String(10))
    cantidad = Column(Float)
    comision = Column(Float, default=0.0)
    estado = Column(String(20), default="completada")
    txid = Column(String(100), nullable=True)
    fecha = Column(DateTime, default=datetime.now)

# Crear tablas
Base.metadata.create_all(bind=engine)
logger.info("✅ Base de datos SQLite inicializada")

# =============================================
# FUNCIONES DE BASE DE DATOS
# =============================================

def obtener_usuario_db(telegram_id):
    session = SessionLocal()
    try:
        usuario = session.query(UsuarioDB).filter_by(telegram_id=telegram_id).first()
        if not usuario:
            usuario = UsuarioDB(
                telegram_id=telegram_id,
                balance_general={"USDT": 0, "TRX": 0, "LTC": 0, "BTC": 0, "BNB": 0, "SOL": 0, "MATIC": 0, "XRP": 0, "XLM": 0, "DOGE": 0, "AVAX": 0, "FTM": 0},
                balance_venta={"USDT": 0, "TRX": 0, "LTC": 0, "BTC": 0, "BNB": 0, "SOL": 0, "MATIC": 0, "XRP": 0, "XLM": 0, "DOGE": 0, "AVAX": 0, "FTM": 0},
                balance_intercambio={"USDT": 0, "TRX": 0, "LTC": 0, "BTC": 0, "BNB": 0, "SOL": 0, "MATIC": 0, "XRP": 0, "XLM": 0, "DOGE": 0, "AVAX": 0, "FTM": 0},
                balance_apuestas={"TRX": 0},
                balance_retiro={"USDT": 0, "TRX": 0, "LTC": 0, "BTC": 0, "BNB": 0, "SOL": 0, "MATIC": 0, "XRP": 0, "XLM": 0, "DOGE": 0, "AVAX": 0, "FTM": 0}
            )
            session.add(usuario)
            session.commit()
            logger.info(f"📝 Nuevo usuario registrado: {telegram_id}")
        return usuario
    finally:
        session.close()

def guardar_usuario_db(usuario):
    session = SessionLocal()
    try:
        session.merge(usuario)
        session.commit()
    finally:
        session.close()

def registrar_transaccion(telegram_id, tipo, moneda, cantidad, comision=0.0, txid=None):
    session = SessionLocal()
    try:
        transaccion = TransaccionDB(
            telegram_id=telegram_id,
            tipo=tipo,
            moneda=moneda,
            cantidad=cantidad,
            comision=comision,
            txid=txid
        )
        session.add(transaccion)
        session.commit()
        return transaccion
    finally:
        session.close()

# =============================================
# FUNCIONES DE VALIDACIÓN
# =============================================

def validar_cantidad(texto):
    try:
        cantidad = float(texto.replace(",", ".").strip())
        if cantidad <= 0:
            return False, "❌ La cantidad debe ser mayor a 0"
        if cantidad > 1000000:
            return False, "❌ La cantidad no puede superar 1,000,000"
        return True, cantidad
    except ValueError:
        return False, "❌ Debes escribir un número válido (ej. 10.50)"

def validar_direccion(direccion, moneda):
    if not direccion or len(direccion) < 10:
        return False, "❌ La dirección es demasiado corta"
    if moneda in ["TRX", "USDT"]:
        if not direccion.startswith("T"):
            return False, "❌ Las direcciones TRX comienzan con 'T'"
        if len(direccion) != 34:
            return False, "❌ Las direcciones TRX tienen 34 caracteres"
    elif moneda in ["LTC"]:
        if not direccion.startswith(("L", "M")):
            return False, "❌ Las direcciones LTC comienzan con 'L' o 'M'"
    elif moneda in ["BTC"]:
        if not direccion.startswith(("1", "3", "bc1")):
            return False, "❌ Dirección BTC no válida"
    return True, "✅ Dirección válida"

# =============================================
# FUNCIONES DE PRECIOS
# =============================================

def obtener_precio_cripto(moneda_id, vs_currency="usd"):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={moneda_id}&vs_currencies={vs_currency}&include_24hr_change=true"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if moneda_id in data:
            precio = data[moneda_id].get(vs_currency, 0)
            cambio_24h = data[moneda_id].get(f"{vs_currency}_24h_change", 0)
            return {"precio": precio, "cambio": cambio_24h, "success": True}
        return {"precio": 0, "cambio": 0, "success": False}
    except:
        return {"precio": 0, "cambio": 0, "success": False}

# =============================================
# CONFIGURACIÓN DEL TOKEN CUC
# =============================================

CONFIG_CUC = {
    "limite_por_usuario": 15,
    "limite_compra_emision": 10,
    "dias_mineria": 15,
    "operaciones_requeridas": 5,
    "total_emitido": 0,
    "total_quemado": 0,
    "total_en_circulacion": 0,
    "ultima_emision": None,
    "precios": [1.0],
    "simbolo": "CUC",
    "nombre": "Peso Cubano Convertible Digital"
}

cuc_emision_actual = {"cantidad": 0, "fecha_emision": None, "vendidos": 0}
usuarios_baneados = []
estadisticas = {"operaciones_hoy": 0, "usuarios_activos": 0, "comisiones_hoy": 0.0}

# =============================================
# MENÚS DEL BOT
# =============================================

def menu_principal():
    keyboard = [
        [InlineKeyboardButton("💰 DEPOSITAR", callback_data="depositar")],
        [InlineKeyboardButton("📌 VENDER", callback_data="vender")],
        [InlineKeyboardButton("🛒 COMPRAR", callback_data="comprar")],
        [InlineKeyboardButton("🔄 INTERCAMBIAR", callback_data="intercambiar")],
        [InlineKeyboardButton("💳 RETIRAR", callback_data="retirar")],
        [InlineKeyboardButton("🪙 CUC TOKEN", callback_data="cuc")],
        [InlineKeyboardButton("💰 STAKING CUC", callback_data="staking")],
        [InlineKeyboardButton("🏦 BANCO DE PRÉSTAMOS", callback_data="banco_prestamos")],
        [InlineKeyboardButton("📊 PRECIOS EN VIVO", callback_data="precios")],
        [InlineKeyboardButton("🎲 APUESTAS", callback_data="apuestas")],
        [InlineKeyboardButton("🎨 CLORTSS", callback_data="clortss")],
        [InlineKeyboardButton("🎁 INVITAR Y GANAR", callback_data="invitar")],
        [InlineKeyboardButton("🔔 ALERTAS", callback_data="alertas")],
        [InlineKeyboardButton("⭐ PLAN PREMIUM", callback_data="premium")],
        [InlineKeyboardButton("📊 MIS ÓRDENES", callback_data="mis_ordenes")],
        [InlineKeyboardButton("⚖️ HISTORIAL", callback_data="historial")],
        [InlineKeyboardButton("🛡️ DISPUTAS", callback_data="disputas")],
        [InlineKeyboardButton("🌐 IDIOMA", callback_data="idioma")],
        [InlineKeyboardButton("💬 AYUDA", callback_data="ayuda")],
    ]
    return InlineKeyboardMarkup(keyboard)

def menu_retirar():
    keyboard = [
        [InlineKeyboardButton("💳 Retirar desde Saldo Retiro (0.5%)", callback_data="retirar_saldo_retiro")],
        [InlineKeyboardButton("💳 Retirar desde Balance General (0.5%)", callback_data="retirar_balance_general")],
        [InlineKeyboardButton("◀️ Volver al Menú", callback_data="volver_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

def menu_cuc():
    keyboard = [
        [InlineKeyboardButton("🛒 COMPRAR CUC", callback_data="cuc_comprar")],
        [InlineKeyboardButton("🎯 ACTIVAR COMISIONES CERO", callback_data="cuc_activar")],
        [InlineKeyboardButton("📊 VENDER CUC", callback_data="cuc_vender")],
        [InlineKeyboardButton("⛏️ MINERÍA CUC", callback_data="cuc_mineria")],
        [InlineKeyboardButton("◀️ Volver", callback_data="volver_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

def menu_depositar():
    keyboard = [
        [InlineKeyboardButton("💵 USDT", callback_data="dep_usdt")],
        [InlineKeyboardButton("🔴 TRX", callback_data="dep_trx")],
        [InlineKeyboardButton("⚡ LTC", callback_data="dep_ltc")],
        [InlineKeyboardButton("🟠 BTC", callback_data="dep_btc")],
        [InlineKeyboardButton("💎 BNB", callback_data="dep_bnb")],
        [InlineKeyboardButton("☀️ SOL", callback_data="dep_sol")],
        [InlineKeyboardButton("🔷 MATIC", callback_data="dep_matic")],
        [InlineKeyboardButton("🌊 XRP", callback_data="dep_xrp")],
        [InlineKeyboardButton("⭐ XLM", callback_data="dep_xlm")],
        [InlineKeyboardButton("🐕 DOGE", callback_data="dep_doge")],
        [InlineKeyboardButton("🔺 AVAX", callback_data="dep_avax")],
        [InlineKeyboardButton("🔶 FTM", callback_data="dep_ftm")],
        [InlineKeyboardButton("◀️ Volver al Menú", callback_data="volver_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

def menu_panel_admin():
    keyboard = [
        [InlineKeyboardButton("💰 Billetera de Usuarios", callback_data="admin_billetera_usuarios")],
        [InlineKeyboardButton("💰 Billetera de Comisiones", callback_data="admin_billetera_comisiones")],
        [InlineKeyboardButton("📊 Estadísticas", callback_data="admin_estadisticas")],
        [InlineKeyboardButton("⚙️ GESTIÓN DE BOTONES", callback_data="admin_gestion_botones")],
        [InlineKeyboardButton("◀️ Volver", callback_data="volver_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

# =============================================
# COMANDOS PRINCIPALES
# =============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        telegram_id = user.id
        
        if telegram_id in usuarios_baneados:
            await update.message.reply_text("❌ You have been banned from this bot.")
            return
        
        usuario = obtener_usuario_db(telegram_id)
        usuario.username = user.username or "sin_usuario"
        usuario.ultima_actividad = datetime.now()
        guardar_usuario_db(usuario)
        
        await update.message.reply_text(
            f"🤖 ¡Bienvenido a Nexus Crypto Bot, {user.first_name}!\n\n"
            "💰 Compra, vende, intercambia y apuesta.\n"
            "✅ 12 monedas soportadas\n"
            "✅ Comisiones: 0.3% operaciones | 0.5% retiros\n"
            "✅ Token CUC: Peso Cubano Convertible Digital\n"
            "✅ Sistema seguro con custodia (escrow)\n\n"
            "Usa el menú para empezar:",
            reply_markup=menu_principal()
        )
        logger.info(f"📝 Nuevo usuario: {user.first_name} (@{user.username}) - ID: {telegram_id}")
    except Exception as e:
        logger.error(f"Error en start: {e}")
        await update.message.reply_text("❌ Ocurrió un error. Intenta de nuevo.")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        telegram_id = user.id
        usuario = obtener_usuario_db(telegram_id)
        
        texto = (
            f"💰 *MI BALANCE COMPLETO*\n"
            f"─────────────────────\n\n"
            f"📌 *BALANCE GENERAL*\n"
            f"💵 USDT: {usuario.balance_general.get('USDT', 0):.2f}\n"
            f"🔴 TRX: {usuario.balance_general.get('TRX', 0):.2f}\n"
            f"⚡ LTC: {usuario.balance_general.get('LTC', 0):.2f}\n\n"
            f"📌 *SALDO RETIRO*\n"
            f"💵 USDT: {usuario.balance_retiro.get('USDT', 0):.2f}\n"
            f"🔴 TRX: {usuario.balance_retiro.get('TRX', 0):.2f}\n"
            f"⚡ LTC: {usuario.balance_retiro.get('LTC', 0):.2f}\n"
            f"─────────────────────\n"
            f"🪙 *SALDO CUC:* {usuario.balance_cuc:.2f}\n"
            f"─────────────────────\n"
            f"⭐ Reputación: {usuario.reputacion:.1f} ★★★★★\n"
            f"📊 Operaciones: {usuario.operaciones}\n"
            f"{'✅ PREMIUM ACTIVADO' if usuario.premium else '🔹 Plan Básico'}"
        )
        
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(texto, parse_mode='Markdown')
        else:
            await update.message.reply_text(texto, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error en balance: {e}")

# =============================================
# RETIRAR
# =============================================

async def retirar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        telegram_id = update.effective_user.id
        usuario = obtener_usuario_db(telegram_id)
        
        texto = (
            "💳 *RETIRAR*\n\n"
            "📌 *SELECCIONA EL ORIGEN DE TUS FONDOS:*\n\n"
            "💰 *SALDO RETIRO* (0.5% comisión)\n"
            f"💵 USDT: {usuario.balance_retiro.get('USDT', 0):.2f}\n"
            f"🔴 TRX: {usuario.balance_retiro.get('TRX', 0):.2f}\n\n"
            "💰 *BALANCE GENERAL* (0.5% comisión)\n"
            f"💵 USDT: {usuario.balance_general.get('USDT', 0):.2f}\n"
            f"🔴 TRX: {usuario.balance_general.get('TRX', 0):.2f}\n\n"
            "💡 *Comisión única: 0.5%*\n"
            "✅ Sin penalización adicional"
        )
        
        await query.edit_message_text(
            texto,
            reply_markup=menu_retirar(),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error en retirar: {e}")

# =============================================
# PRECIOS EN VIVO
# =============================================

async def precios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        telegram_id = update.effective_user.id
        
        if telegram_id in usuarios_baneados:
            await query.edit_message_text("❌ You have been banned from this bot.")
            return
        
        trx = obtener_precio_cripto("tron", "usd")
        ltc = obtener_precio_cripto("litecoin", "usd")
        btc = obtener_precio_cripto("bitcoin", "usd")
        
        texto = (
            f"📊 *PRECIOS EN VIVO*\n"
            f"─────────────────────────────\n\n"
            f"🔴 *TRON (TRX)*\n"
            f"💰 USDT: {trx['precio']:.4f}\n"
            f"📈 24h: {trx['cambio']:+.2f}%\n\n"
            f"⚡ *LITECOIN (LTC)*\n"
            f"💰 USDT: {ltc['precio']:.2f}\n"
            f"📈 24h: {ltc['cambio']:+.2f}%\n\n"
            f"🟠 *BITCOIN (BTC)*\n"
            f"💰 USDT: {btc['precio']:,.0f}\n"
            f"📈 24h: {btc['cambio']:+.2f}%\n"
            f"─────────────────────────────\n"
            f"🔄 *Última actualización:* {datetime.now().strftime('%H:%M')}\n"
        )
        
        keyboard = [[InlineKeyboardButton("🔄 ACTUALIZAR", callback_data="precios")]]
        
        await query.edit_message_text(
            texto,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error en precios: {e}")

# =============================================
# CUC - TOKEN
# =============================================

async def cuc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        telegram_id = update.effective_user.id
        usuario = obtener_usuario_db(telegram_id)
        
        await query.edit_message_text(
            f"🪙 *CUC - PESO CUBANO CONVERTIBLE DIGITAL*\n\n"
            f"📋 *¿QUÉ ES CUC?*\n"
            f"CUC es un token de utilidad que vale 1 USDT.\n\n"
            f"💰 *CUC DISPONIBLES:* {cuc_emision_actual['cantidad']}\n"
            f"💰 *MI SALDO:* {usuario.balance_cuc:.2f}\n\n"
            f"📋 *OPCIONES:*",
            reply_markup=menu_cuc(),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error en cuc: {e}")

async def cuc_activar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        telegram_id = update.effective_user.id
        usuario = obtener_usuario_db(telegram_id)
        
        if usuario.balance_cuc < 1:
            await query.edit_message_text("❌ No tienes CUC suficientes. Necesitas 1 CUC.")
            return
        
        keyboard = [
            [InlineKeyboardButton("🔥 ACTIVAR", callback_data="cuc_activar_confirmar")],
            [InlineKeyboardButton("❌ CANCELAR", callback_data="cuc")],
        ]
        
        await query.edit_message_text(
            f"🎯 *ACTIVAR COMISIONES CERO*\n\n"
            f"⚠️ *AL ACTIVAR:*\n"
            f"- 1 CUC se descontará de tu saldo\n"
            f"- Tus comisiones serán 0% durante 24 horas\n\n"
            f"💰 *Saldo de CUC actual:* {usuario.balance_cuc:.2f}\n"
            f"⏳ *Saldo después:* {usuario.balance_cuc - 1:.2f}\n\n"
            f"⏳ *Duración:* 24 horas",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error en cuc_activar: {e}")

async def cuc_activar_confirmar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        telegram_id = update.effective_user.id
        usuario = obtener_usuario_db(telegram_id)
        
        if usuario.balance_cuc < 1:
            await query.edit_message_text("❌ No tienes CUC suficientes.")
            return
        
        usuario.balance_cuc -= 1
        usuario.premium = True
        usuario.fecha_premium = datetime.now() + timedelta(days=1)
        guardar_usuario_db(usuario)
        
        await query.edit_message_text(
            f"✅ *¡COMISIONES CERO ACTIVADAS!*\n\n"
            f"✅ Has activado comisiones 0% por 24 horas.\n\n"
            f"💰 Saldo de CUC: {usuario.balance_cuc:.2f}\n"
            f"⏳ Válido hasta: {usuario.fecha_premium.strftime('%d/%m/%Y %H:%M')}\n\n"
            f"💡 El CUC ha sido eliminado permanentemente.",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error en cuc_activar_confirmar: {e}")

# =============================================
# PANEL DE ADMINISTRADOR
# =============================================

async def panel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        
        if user_id != ADMINISTRADOR_ID:
            await update.message.reply_text("❌ No tienes permiso para acceder a este panel.")
            logger.warning(f"⚠️ Intento de acceso no autorizado al panel: {user_id}")
            return
        
        session = SessionLocal()
        try:
            total_usuarios = session.query(UsuarioDB).count()
            usuarios_activos = session.query(UsuarioDB).filter(
                UsuarioDB.ultima_actividad > (datetime.now() - timedelta(days=1))
            ).count()
        finally:
            session.close()
        
        texto = (
            f"🛡️ *PANEL DE ADMINISTRADOR - NEXUS CRYPTO BOT*\n\n"
            f"👤 Administrador: @{update.effective_user.username}\n"
            f"📅 Último acceso: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
            f"📊 *ESTADÍSTICAS*\n"
            "─────────────────────────────\n"
            f"👥 Usuarios totales: {total_usuarios}\n"
            f"🟢 Activos hoy: {usuarios_activos}\n"
            f"🪙 CUC en circulación: {CONFIG_CUC['total_en_circulacion']}\n"
            f"🔥 CUC quemados: {CONFIG_CUC['total_quemado']}\n"
            f"💰 Comisiones hoy: ${estadisticas.get('comisiones_hoy', 0):.2f}\n\n"
            "📋 *SELECCIONA UNA OPCIÓN:*"
        )
        
        await update.message.reply_text(
            texto,
            reply_markup=menu_panel_admin(),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error en panel_admin: {e}")

# =============================================
# MANEJADOR DE CALLBACKS
# =============================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        data = query.data
        user_id = update.effective_user.id
        
        logger.info(f"📌 Callback: {data} - Usuario: {user_id}")
        
        if data == "volver_menu":
            await query.edit_message_text(
                "📋 *Menú Principal*\n\nSelecciona una opción:",
                reply_markup=menu_principal(),
                parse_mode='Markdown'
            )
            return
        
        # Retirar
        if data == "retirar":
            await retirar(update, context)
            return
        
        # Precios
        if data == "precios":
            await precios(update, context)
            return
        
        # CUC
        if data == "cuc":
            await cuc(update, context)
            return
        
        if data == "cuc_activar":
            await cuc_activar(update, context)
            return
        
        if data == "cuc_activar_confirmar":
            await cuc_activar_confirmar(update, context)
            return
        
        # Balance
        if data == "balance":
            await balance(update, context)
            return
        
        # Depósito
        if data == "depositar":
            await query.edit_message_text(
                "💰 *DEPOSITAR*\n\n"
                "Selecciona la moneda a depositar:",
                reply_markup=menu_depositar(),
                parse_mode='Markdown'
            )
            return
        
        if data.startswith("dep_"):
            moneda = data.replace("dep_", "").upper()
            await query.edit_message_text(
                f"💰 *DEPOSITAR {moneda}*\n\n"
                f"📎 *Dirección de depósito:*\n"
                f"`{moneda}...Generada`\n\n"
                f"⏳ Confirmación: 3 bloques (~3-5 min)\n"
                f"💡 Envía SOLO {moneda} a esta dirección.\n"
                f"⚠️ Otras monedas se perderán.\n\n"
                f"🔹 *Estado:* Esperando depósito...\n\n"
                f"Cuando deposites, el bot acreditará los fondos\n"
                f"en tu *Balance General* automáticamente.",
                parse_mode='Markdown'
            )
            return
        
        # Otras opciones
        await query.edit_message_text(
            "✅ Opción seleccionada. Implementación en desarrollo.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error en callback_handler: {e}")
        try:
            await query.edit_message_text("❌ Ocurrió un error. Intenta de nuevo.")
        except:
            pass

# =============================================
# FUNCIÓN PRINCIPAL
# =============================================

if __name__ == "__main__":
    try:
        if not TOKEN:
            logger.error("❌ BOT_TOKEN no configurado")
            sys.exit(1)
        
        app = Application.builder().token(TOKEN).build()
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("balance", balance))
        
        app.add_handler(CommandHandler(COMANDO_PANEL, panel_admin))
        
        app.add_handler(CallbackQueryHandler(callback_handler))
        
        logger.info(f"✅ Nexus Crypto Bot iniciado. Panel: /{COMANDO_PANEL}")
        app.run_polling(allowed_updates=["message", "callback_query"])
        
    except Exception as e:
        logger.error(f"❌ Error fatal: {e}")
        sys.exit(1)
