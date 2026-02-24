#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت تليجرام متكامل للتحكم بالقنوات - نظام يدوي
المطور: @Allawi04
الإصدار: 3.0
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import os
import json
import re
from enum import Enum
import pytz
from dataclasses import dataclass
from collections import defaultdict
import html
import traceback
from uuid import uuid4

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, Chat
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    ChatMemberHandler
)
from telegram.constants import ParseMode, ChatType
from telegram.error import TelegramError

from supabase import create_client, Client

# ==================== التهيئة والإعدادات ====================

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# إعدادات البوت
BOT_TOKEN = "8625525956:AAGYmiC0L886KLIntvKCS0xLArMRo_62zOc"
ADMIN_ID = 6130994941
ADMIN_USERNAME = "Allawi04"

# إعدادات Supabase
SUPABASE_URL = "https://wregsrzadpgrccuaeoqg.supabase.co"
SUPABASE_KEY = "sb_publishable_wxK2zSkofxB1-V4FrQyvlg_jrBpMCM0"

# إعدادات الأسعار
VIP_PRICE = 25  # سعر VIP بالنجوم (للعرض فقط)
MAX_FREE_CHANNELS = 2
MAX_VIP_CHANNELS = 10
FREE_TRIAL_DAYS = 14
VIP_DAYS = 30

# المناطق الزمنية
TIMEZONE = pytz.timezone('Asia/Baghdad')

# ==================== حالات المحادثة ====================

# حالات إضافة القناة
ADD_CHANNEL_WAITING_LINK = 1
ADD_CHANNEL_VERIFYING = 2

# حالات تفعيل VIP (للمدير)
ACTIVATE_VIP_WAITING_USER_ID = 3
ACTIVATE_VIP_WAITING_DAYS = 4

# حالات الإذاعة
BROADCAST_WAITING_MESSAGE = 5
BROADCAST_CONFIRM = 6

# حالات تغيير السعر
CHANGE_PRICE_WAITING = 7

# ==================== نماذج البيانات ====================

@dataclass
class ChannelData:
    """بيانات القناة"""
    id: int
    link: str
    title: str
    added_date: datetime
    is_active: bool = True
    
    def to_dict(self):
        return {
            'id': self.id,
            'link': self.link,
            'title': self.title,
            'added_date': self.added_date.isoformat() if isinstance(self.added_date, datetime) else self.added_date,
            'is_active': self.is_active
        }
    
    @classmethod
    def from_dict(cls, data):
        if isinstance(data.get('added_date'), str):
            data['added_date'] = datetime.fromisoformat(data['added_date'])
        return cls(**data)

@dataclass
class UserSettings:
    """إعدادات المستخدم"""
    ban_new_members: bool = False
    ban_leavers: bool = False
    ban_no_username: bool = False
    
    def to_dict(self):
        return {
            'ban_new_members': self.ban_new_members,
            'ban_leavers': self.ban_leavers,
            'ban_no_username': self.ban_no_username
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(
            ban_new_members=data.get('ban_new_members', False),
            ban_leavers=data.get('ban_leavers', False),
            ban_no_username=data.get('ban_no_username', False)
        )

@dataclass
class UserData:
    """بيانات المستخدم الكاملة"""
    user_id: int
    username: Optional[str]
    first_name: str
    join_date: datetime
    expiry_date: datetime
    is_vip: bool = False
    is_active: bool = True
    is_banned: bool = False
    channels: List[ChannelData] = None
    settings: UserSettings = None
    total_payments: int = 0
    last_active: Optional[datetime] = None
    
    def __post_init__(self):
        if self.channels is None:
            self.channels = []
        if self.settings is None:
            self.settings = UserSettings()
    
    def to_dict(self):
        return {
            'user_id': self.user_id,
            'username': self.username,
            'first_name': self.first_name,
            'join_date': self.join_date.isoformat() if isinstance(self.join_date, datetime) else self.join_date,
            'expiry_date': self.expiry_date.isoformat() if isinstance(self.expiry_date, datetime) else self.expiry_date,
            'is_vip': self.is_vip,
            'is_active': self.is_active,
            'is_banned': self.is_banned,
            'channels': [c.to_dict() for c in self.channels],
            'settings': self.settings.to_dict(),
            'total_payments': self.total_payments,
            'last_active': self.last_active.isoformat() if isinstance(self.last_active, datetime) else self.last_active
        }
    
    @classmethod
    def from_dict(cls, data):
        # تحويل التواريخ
        if isinstance(data.get('join_date'), str):
            data['join_date'] = datetime.fromisoformat(data['join_date'])
        if isinstance(data.get('expiry_date'), str):
            data['expiry_date'] = datetime.fromisoformat(data['expiry_date'])
        if isinstance(data.get('last_active'), str):
            data['last_active'] = datetime.fromisoformat(data['last_active'])
        
        # تحويل القنوات
        channels = []
        for c in data.get('channels', []):
            if isinstance(c, dict):
                channels.append(ChannelData.from_dict(c))
        
        # تحويل الإعدادات
        settings = UserSettings.from_dict(data.get('settings', {}))
        
        return cls(
            user_id=data['user_id'],
            username=data.get('username'),
            first_name=data.get('first_name', ''),
            join_date=data['join_date'],
            expiry_date=data['expiry_date'],
            is_vip=data.get('is_vip', False),
            is_active=data.get('is_active', True),
            is_banned=data.get('is_banned', False),
            channels=channels,
            settings=settings,
            total_payments=data.get('total_payments', 0),
            last_active=data.get('last_active')
        )

# ==================== قاعدة البيانات ====================

class Database:
    """إدارة قاعدة البيانات باستخدام Supabase"""
    
    def __init__(self, url: str, key: str):
        self.client: Client = create_client(url, key)
        self.cache = {}
        self.cache_timeout = 300  # 5 دقائق
    
    async def init_tables(self):
        """إنشاء الجداول إذا لم تكن موجودة"""
        try:
            response = self.client.table('users').select("*").limit(1).execute()
            logger.info("✅ Database connected successfully")
        except Exception as e:
            logger.error(f"❌ Database initialization error: {e}")
    
    async def get_user(self, user_id: int) -> Optional[UserData]:
        """الحصول على بيانات مستخدم"""
        try:
            cache_key = f"user_{user_id}"
            if cache_key in self.cache:
                cache_time, user_data = self.cache[cache_key]
                if (datetime.now() - cache_time).seconds < self.cache_timeout:
                    return user_data
            
            response = self.client.table('users').select("*").eq('user_id', user_id).execute()
            
            if response.data:
                user_data = UserData.from_dict(response.data[0])
                self.cache[cache_key] = (datetime.now(), user_data)
                return user_data
            return None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    async def create_user(self, user_id: int, username: str = None, first_name: str = None) -> UserData:
        """إنشاء مستخدم جديد"""
        try:
            now = datetime.now(TIMEZONE)
            expiry_date = now + timedelta(days=FREE_TRIAL_DAYS)
            
            new_user = UserData(
                user_id=user_id,
                username=username,
                first_name=first_name or "",
                join_date=now,
                expiry_date=expiry_date,
                is_vip=False,
                is_active=True,
                is_banned=False,
                channels=[],
                settings=UserSettings(),
                total_payments=0,
                last_active=now
            )
            
            data = new_user.to_dict()
            response = self.client.table('users').insert(data).execute()
            
            if response.data:
                logger.info(f"✅ Created new user: {user_id}")
                return new_user
            else:
                raise Exception("Failed to create user")
        except Exception as e:
            logger.error(f"Error creating user {user_id}: {e}")
            raise
    
    async def update_user(self, user_id: int, **kwargs) -> bool:
        """تحديث بيانات مستخدم"""
        try:
            response = self.client.table('users').update(kwargs).eq('user_id', user_id).execute()
            
            cache_key = f"user_{user_id}"
            if cache_key in self.cache:
                user = self.cache[cache_key][1]
                for key, value in kwargs.items():
                    if hasattr(user, key):
                        setattr(user, key, value)
                self.cache[cache_key] = (datetime.now(), user)
            
            return bool(response.data)
        except Exception as e:
            logger.error(f"Error updating user {user_id}: {e}")
            return False
    
    async def get_or_create_user(self, user_id: int, username: str = None, first_name: str = None) -> UserData:
        """الحصول على المستخدم أو إنشاؤه"""
        user = await self.get_user(user_id)
        if not user:
            user = await self.create_user(user_id, username, first_name)
        else:
            await self.update_user(user_id, last_active=datetime.now(TIMEZONE).isoformat())
        return user
    
    async def get_all_users(self) -> List[UserData]:
        """الحصول على جميع المستخدمين"""
        try:
            response = self.client.table('users').select("*").execute()
            return [UserData.from_dict(u) for u in response.data]
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    async def add_channel(self, user_id: int, channel_data: ChannelData) -> Tuple[bool, str]:
        """إضافة قناة لمستخدم"""
        try:
            user = await self.get_user(user_id)
            if not user:
                return False, "المستخدم غير موجود"
            
            max_channels = MAX_VIP_CHANNELS if user.is_vip else MAX_FREE_CHANNELS
            if len(user.channels) >= max_channels:
                return False, f"لا يمكنك إضافة أكثر من {max_channels} قنوات"
            
            for ch in user.channels:
                if ch.id == channel_data.id:
                    return False, "هذه القناة مضافة بالفعل"
            
            channels = [c.to_dict() for c in user.channels]
            channels.append(channel_data.to_dict())
            
            success = await self.update_user(user_id, channels=channels)
            if success:
                return True, f"✅ تم إضافة القناة بنجاح. لديك الآن {len(user.channels) + 1}/{max_channels} قنوات"
            else:
                return False, "❌ حدث خطأ في إضافة القناة"
        except Exception as e:
            logger.error(f"Error adding channel for user {user_id}: {e}")
            return False, "❌ حدث خطأ في إضافة القناة"
    
    async def remove_channel(self, user_id: int, channel_id: int) -> bool:
        """حذف قناة من مستخدم"""
        try:
            user = await self.get_user(user_id)
            if not user:
                return False
            
            channels = [c.to_dict() for c in user.channels if c.id != channel_id]
            return await self.update_user(user_id, channels=channels)
        except Exception as e:
            logger.error(f"Error removing channel for user {user_id}: {e}")
            return False
    
    async def update_settings(self, user_id: int, setting: str, value: bool) -> bool:
        """تحديث إعدادات المستخدم"""
        try:
            user = await self.get_user(user_id)
            if not user:
                return False
            
            settings = user.settings.to_dict()
            settings[setting] = value
            
            return await self.update_user(user_id, settings=settings)
        except Exception as e:
            logger.error(f"Error updating settings for user {user_id}: {e}")
            return False
    
    async def activate_vip(self, user_id: int, days: int) -> bool:
        """تفعيل VIP لمستخدم (للمدير)"""
        try:
            user = await self.get_user(user_id)
            if not user:
                return False
            
            now = datetime.now(TIMEZONE)
            current_expiry = user.expiry_date
            
            if current_expiry < now:
                new_expiry = now + timedelta(days=days)
            else:
                new_expiry = current_expiry + timedelta(days=days)
            
            return await self.update_user(
                user_id, 
                expiry_date=new_expiry.isoformat(),
                is_vip=True,
                total_payments=user.total_payments + 1
            )
        except Exception as e:
            logger.error(f"Error activating VIP for user {user_id}: {e}")
            return False
    
    async def get_statistics(self) -> Dict[str, Any]:
        """الحصول على إحصائيات البوت"""
        users = await self.get_all_users()
        now = datetime.now(TIMEZONE)
        
        total_users = len(users)
        vip_users = sum(1 for u in users if u.is_vip)
        active_users = sum(1 for u in users if u.expiry_date > now and u.is_active and not u.is_banned)
        expired_users = sum(1 for u in users if u.expiry_date <= now and u.is_active and not u.is_banned)
        banned_users = sum(1 for u in users if u.is_banned)
        
        today_start = datetime(now.year, now.month, now.day, tzinfo=TIMEZONE)
        new_today = sum(1 for u in users if u.join_date >= today_start)
        
        total_channels = sum(len(u.channels) for u in users)
        
        return {
            'total_users': total_users,
            'vip_users': vip_users,
            'active_users': active_users,
            'expired_users': expired_users,
            'banned_users': banned_users,
            'new_today': new_today,
            'total_channels': total_channels
        }

# ==================== تهيئة قاعدة البيانات ====================

db = Database(SUPABASE_URL, SUPABASE_KEY)

# ==================== أدوات مساعدة ====================

class Helpers:
    """كلاس للأدوات المساعدة"""
    
    @staticmethod
    def format_date(date: datetime) -> str:
        """تنسيق التاريخ"""
        if not date:
            return "غير معروف"
        return date.strftime("%Y-%m-%d %H:%M")
    
    @staticmethod
    def format_remaining_days(expiry_date: datetime) -> str:
        """تنسيق الأيام المتبقية"""
        now = datetime.now(TIMEZONE)
        if expiry_date <= now:
            return "منتهي"
        
        delta = expiry_date - now
        days = delta.days
        hours = delta.seconds // 3600
        
        if days > 0:
            return f"{days} يوم و {hours} ساعة"
        else:
            return f"{hours} ساعة"
    
    @staticmethod
    def extract_channel_username(link: str) -> Optional[str]:
        """استخراج يوزر القناة من الرابط"""
        patterns = [
            r't\.me/([a-zA-Z0-9_]+)',
            r'telegram\.me/([a-zA-Z0-9_]+)',
            r'@([a-zA-Z0-9_]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, link)
            if match:
                return match.group(1)
        return None

helpers = Helpers()

# ==================== لوحة المفاتيح ====================

class Keyboards:
    """كلاس لوحات المفاتيح"""
    
    @staticmethod
    def main_menu(user_id: int, is_vip: bool = False) -> InlineKeyboardMarkup:
        """لوحة المفاتيح الرئيسية"""
        keyboard = []
        
        # زر إضافة قناة
        keyboard.append([InlineKeyboardButton("📢 إضافة قناة جديدة", callback_data="add_channel")])
        
        # زر قنواتي (إذا وجدت قنوات)
        # سنتحقق من وجود قنوات عند الاستدعاء
        
        # أزرار التحكم
        keyboard.extend([
            [
                InlineKeyboardButton("🚫 حظر المنضمين", callback_data="toggle_ban_new_members"),
                InlineKeyboardButton("🚫 حظر المغادرين", callback_data="toggle_ban_leavers")
            ],
            [
                InlineKeyboardButton("🚫 حظر بدون يوزر", callback_data="toggle_ban_no_username")
            ],
            [
                InlineKeyboardButton("⭐ اشتراك VIP", callback_data="vip_menu"),
                InlineKeyboardButton("📞 تواصل معنا", url=f"https://t.me/{ADMIN_USERNAME}")
            ]
        ])
        
        # زر لوحة التحكم للمدير
        if user_id == ADMIN_ID:
            keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel")])
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def vip_menu() -> InlineKeyboardMarkup:
        """قائمة VIP"""
        keyboard = [
            [InlineKeyboardButton("💫 شراء اشتراك VIP", callback_data="buy_vip")],
            [InlineKeyboardButton("ℹ️ مميزات VIP", callback_data="vip_features")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def admin_panel() -> InlineKeyboardMarkup:
        """لوحة تحكم المدير"""
        keyboard = [
            [InlineKeyboardButton("📊 إحصائيات شاملة", callback_data="admin_stats")],
            [InlineKeyboardButton("💰 تغيير سعر VIP", callback_data="admin_change_price")],
            [InlineKeyboardButton("🔧 وضع الصيانة", callback_data="admin_maintenance")],
            [InlineKeyboardButton("📢 إذاعة للجميع", callback_data="admin_broadcast")],
            [InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="admin_users")],
            [InlineKeyboardButton("⭐ تفعيل VIP", callback_data="admin_activate_vip")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def channels_menu(channels: List[ChannelData], page: int = 0, items_per_page: int = 5) -> InlineKeyboardMarkup:
        """قائمة القنوات مع ترقيم الصفحات"""
        keyboard = []
        
        start = page * items_per_page
        end = start + items_per_page
        page_channels = channels[start:end]
        
        for channel in page_channels:
            btn_text = f"❌ {channel.title[:20]}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"delete_channel_{channel.id}")])
        
        # أزرار الترقيم
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"channels_page_{page-1}"))
        if end < len(channels):
            nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"channels_page_{page+1}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")])
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
        """لوحة تأكيد"""
        keyboard = [
            [
                InlineKeyboardButton("✅ نعم", callback_data=f"confirm_{action}"),
                InlineKeyboardButton("❌ لا", callback_data=f"cancel_{action}")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

# ==================== معالجي الأوامر ====================

class CommandHandlers:
    """معالجي الأوامر"""
    
    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /start"""
        user = update.effective_user
        
        try:
            db_user = await db.get_or_create_user(user.id, user.username, user.first_name)
            
            if db_user.is_banned:
                await update.message.reply_text(
                    "⛔ لقد تم حظرك من استخدام البوت.\n"
                    f"للتواصل مع الدعم: @{ADMIN_USERNAME}"
                )
                return
            
            is_active = db_user.expiry_date > datetime.now(TIMEZONE)
            remaining = helpers.format_remaining_days(db_user.expiry_date)
            
            # رسالة الترحيب مع طلب الاشتراك المباشر
            welcome_text = (
                f"👋 أهلاً بك {db_user.first_name} في بوت حماية القنوات!\n\n"
                f"📊 حالتك الحالية:\n"
                f"{'✅' if is_active else '❌'} الاشتراك: {'نشط' if is_active else 'منتهي'}\n"
                f"⏱ المتبقي: {remaining}\n"
                f"{'⭐' if db_user.is_vip else '💫'} النوع: {'VIP' if db_user.is_vip else 'مجاني'}\n"
                f"📢 القنوات: {len(db_user.channels)}/{MAX_VIP_CHANNELS if db_user.is_vip else MAX_FREE_CHANNELS}\n\n"
                f"🎁 لقد حصلت على {FREE_TRIAL_DAYS} يوم هدية!\n\n"
                f"💬 للاشتراك VIP: اضغط على زر 'اشتراك VIP' ثم تواصل مع @{ADMIN_USERNAME}"
            )
            
            await update.message.reply_text(
                welcome_text,
                reply_markup=Keyboards.main_menu(user.id, db_user.is_vip)
            )
            
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await update.message.reply_text("❌ حدث خطأ. الرجاء المحاولة لاحقاً.")
    
    @staticmethod
    async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج الضغط على الأزرار"""
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        data = query.data
        
        try:
            db_user = await db.get_or_create_user(user.id, user.username, user.first_name)
            
            if db_user.is_banned and user.id != ADMIN_ID:
                await query.edit_message_text("⛔ أنت محظور من استخدام البوت.")
                return
            
            if data == "back_to_main":
                await CommandHandlers.show_main_menu(update, context)
            
            elif data == "add_channel":
                await CommandHandlers.add_channel_start(update, context)
            
            elif data == "my_channels":
                await CommandHandlers.show_channels(update, context)
            
            elif data.startswith("channels_page_"):
                page = int(data.split("_")[2])
                await CommandHandlers.show_channels(update, context, page)
            
            elif data.startswith("delete_channel_"):
                channel_id = int(data.split("_")[2])
                context.user_data['channel_to_delete'] = channel_id
                await query.edit_message_text(
                    "🗑 هل أنت متأكد من حذف هذه القناة؟",
                    reply_markup=Keyboards.confirm_keyboard("delete_channel")
                )
            
            elif data == "confirm_delete_channel":
                channel_id = context.user_data.get('channel_to_delete')
                if channel_id:
                    await db.remove_channel(user.id, channel_id)
                    await query.edit_message_text(
                        "✅ تم حذف القناة بنجاح",
                        reply_markup=Keyboards.main_menu(user.id, db_user.is_vip)
                    )
            
            elif data == "cancel_delete_channel":
                await query.edit_message_text(
                    "تم إلغاء الحذف",
                    reply_markup=Keyboards.main_menu(user.id, db_user.is_vip)
                )
            
            elif data.startswith("toggle_"):
                setting = data.replace("toggle_", "")
                current_value = getattr(db_user.settings, setting, False)
                new_value = not current_value
                
                await db.update_settings(user.id, setting, new_value)
                
                setting_names = {
                    'ban_new_members': 'حظر المنضمين',
                    'ban_leavers': 'حظر المغادرين',
                    'ban_no_username': 'حظر بدون يوزر'
                }
                
                await query.edit_message_text(
                    f"✅ تم {'تفعيل' if new_value else 'تعطيل'} {setting_names.get(setting, setting)}",
                    reply_markup=Keyboards.main_menu(user.id, db_user.is_vip)
                )
            
            elif data == "vip_menu":
                await CommandHandlers.vip_menu(update, context)
            
            elif data == "buy_vip":
                await query.edit_message_text(
                    f"💫 **للاشتراك VIP:**\n\n"
                    f"1️⃣ السعر: {VIP_PRICE} نجمة تليجرام\n"
                    f"2️⃣ المدة: {VIP_DAYS} يوم\n"
                    f"3️⃣ المميزات: {MAX_VIP_CHANNELS} قنوات\n\n"
                    f"📞 **للشراء، تواصل مع المسؤول:**\n"
                    f"@{ADMIN_USERNAME}\n\n"
                    f"⚠️ أرسل له رسالة تحتوي على:\n"
                    f"`مرحبا اريد اشتراك بالبوت شنو السعر`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💬 مراسلة المسؤول", url=f"https://t.me/{ADMIN_USERNAME}")],
                        [InlineKeyboardButton("📋 نسخ الرسالة", callback_data="copy_message")],
                        [InlineKeyboardButton("🔙 رجوع", callback_data="vip_menu")]
                    ])
                )
            
            elif data == "copy_message":
                await query.answer("تم النسخ! أرسل الرسالة للمسؤول", show_alert=True)
                # نسخ الرسالة للحافظة - المستخدم ينسخها يدوياً
            
            elif data == "vip_features":
                text = (
                    "🌟 **مميزات الاشتراك VIP** 🌟\n\n"
                    f"• إضافة حتى **{MAX_VIP_CHANNELS}** قنوات\n"
                    f"• مدة الاشتراك: **{VIP_DAYS}** يوم\n"
                    "• دعم فني متميز\n"
                    "• أولوية في المعالجة\n"
                    "• مميزات حصرية قادمة\n\n"
                    f"💰 السعر: **{VIP_PRICE}** نجمة تليجرام"
                )
                await query.edit_message_text(
                    text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=Keyboards.vip_menu()
                )
            
            elif data == "admin_panel" and user.id == ADMIN_ID:
                await CommandHandlers.admin_panel(update, context)
            
            elif data == "admin_stats" and user.id == ADMIN_ID:
                await CommandHandlers.admin_stats(update, context)
            
            elif data == "admin_change_price" and user.id == ADMIN_ID:
                await query.edit_message_text(
                    f"💰 **تغيير سعر VIP**\n\n"
                    f"السعر الحالي: {VIP_PRICE} نجمة\n\n"
                    "أرسل السعر الجديد (رقم فقط):",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 إلغاء", callback_data="admin_panel")
                    ]])
                )
                context.user_data['awaiting_price'] = True
                return CHANGE_PRICE_WAITING
            
            elif data == "admin_maintenance" and user.id == ADMIN_ID:
                current_mode = context.bot_data.get('maintenance_mode', False)
                
                if current_mode:
                    context.bot_data['maintenance_mode'] = False
                    text = "✅ تم إيقاف وضع الصيانة. البوت يعمل بشكل طبيعي."
                else:
                    context.bot_data['maintenance_mode'] = True
                    text = "🔧 تم تفعيل وضع الصيانة. المستخدمون العاديون لا يمكنهم استخدام البوت."
                
                await query.edit_message_text(text, reply_markup=Keyboards.admin_panel())
            
            elif data == "admin_broadcast" and user.id == ADMIN_ID:
                await query.edit_message_text(
                    "📢 **إذاعة للجميع**\n\n"
                    "أرسل الرسالة التي تريد إذاعتها (نص، صورة، فيديو، ...)\n\n"
                    "لإلغاء: /cancel",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 إلغاء", callback_data="admin_panel")
                    ]])
                )
                context.user_data['awaiting_broadcast'] = True
                return BROADCAST_WAITING_MESSAGE
            
            elif data == "admin_users" and user.id == ADMIN_ID:
                users = await db.get_all_users()
                users.sort(key=lambda x: x.join_date, reverse=True)
                
                text = "👥 **آخر 10 مستخدمين:**\n\n"
                
                for i, u in enumerate(users[:10], 1):
                    status = "✅" if u.expiry_date > datetime.now(TIMEZONE) else "❌"
                    vip = "⭐" if u.is_vip else "💫"
                    text += f"{i}. {vip} {u.first_name[:15]} - `{u.user_id}`\n"
                    text += f"   • الحالة: {status}\n"
                    text += f"   • القنوات: {len(u.channels)}\n\n"
                
                keyboard = [
                    [InlineKeyboardButton("⭐ تفعيل VIP", callback_data="admin_activate_vip")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
                ]
                
                await query.edit_message_text(
                    text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            elif data == "admin_activate_vip" and user.id == ADMIN_ID:
                await query.edit_message_text(
                    "⭐ **تفعيل VIP لمستخدم**\n\n"
                    "أرسل **ايدي المستخدم** (رقم فقط):\n"
                    "مثال: `123456789`\n\n"
                    "للإلغاء: /cancel",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 إلغاء", callback_data="admin_panel")
                    ]])
                )
                context.user_data['awaiting_activate_user'] = True
                return ACTIVATE_VIP_WAITING_USER_ID
            
        except Exception as e:
            logger.error(f"Error in callback handler: {e}")
            await query.edit_message_text("❌ حدث خطأ. الرجاء المحاولة لاحقاً.")
    
    @staticmethod
    async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض القائمة الرئيسية"""
        query = update.callback_query
        user_id = update.effective_user.id
        
        db_user = await db.get_user(user_id)
        
        # التحقق من وجود قنوات لإظهار زر "قنواتي"
        keyboard = []
        keyboard.append([InlineKeyboardButton("📢 إضافة قناة جديدة", callback_data="add_channel")])
        
        if db_user and db_user.channels:
            channels_text = f"📋 قنواتي ({len(db_user.channels)}/{MAX_VIP_CHANNELS if db_user.is_vip else MAX_FREE_CHANNELS})"
            keyboard.append([InlineKeyboardButton(channels_text, callback_data="my_channels")])
        
        keyboard.extend([
            [
                InlineKeyboardButton("🚫 حظر المنضمين", callback_data="toggle_ban_new_members"),
                InlineKeyboardButton("🚫 حظر المغادرين", callback_data="toggle_ban_leavers")
            ],
            [
                InlineKeyboardButton("🚫 حظر بدون يوزر", callback_data="toggle_ban_no_username")
            ],
            [
                InlineKeyboardButton("⭐ اشتراك VIP", callback_data="vip_menu"),
                InlineKeyboardButton("📞 تواصل معنا", url=f"https://t.me/{ADMIN_USERNAME}")
            ]
        ])
        
        if user_id == ADMIN_ID:
            keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel")])
        
        await query.edit_message_text(
            "القائمة الرئيسية",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    @staticmethod
    async def add_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """بدء إضافة قناة"""
        query = update.callback_query
        user_id = update.effective_user.id
        
        db_user = await db.get_user(user_id)
        max_channels = MAX_VIP_CHANNELS if db_user and db_user.is_vip else MAX_FREE_CHANNELS
        
        if db_user and len(db_user.channels) >= max_channels:
            await query.edit_message_text(
                f"❌ لقد وصلت للحد الأقصى ({max_channels} قنوات)\n"
                f"قم بحذف قناة قديمة أو اشترك VIP",
                reply_markup=Keyboards.main_menu(user_id, db_user.is_vip)
            )
            return
        
        await query.edit_message_text(
            "📝 **إضافة قناة جديدة**\n\n"
            "أرسل رابط القناة:\n"
            "مثال: `https://t.me/username`\n\n"
            "📌 **شروط الإضافة:**\n"
            "• البوت مشرف في القناة بكل الصلاحيات\n"
            "• الرابط صحيح\n\n"
            "للإلغاء: /cancel",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 إلغاء", callback_data="back_to_main")
            ]])
        )
        
        context.user_data['awaiting_channel'] = True
        return ADD_CHANNEL_WAITING_LINK
    
    @staticmethod
    async def handle_channel_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج رابط القناة"""
        if not context.user_data.get('awaiting_channel'):
            return
        
        message = update.message
        user_id = update.effective_user.id
        link = message.text.strip()
        
        channel_username = helpers.extract_channel_username(link)
        if not channel_username:
            await message.reply_text(
                "❌ رابط غير صحيح!\nأرسل رابط صحيح مثل: https://t.me/username",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 إلغاء", callback_data="back_to_main")
                ]])
            )
            return
        
        status_msg = await message.reply_text(f"🔍 جاري التحقق من القناة @{channel_username}...")
        
        try:
            chat = await context.bot.get_chat(f"@{channel_username}")
            
            bot_member = await chat.get_member(context.bot.id)
            
            if bot_member.status not in ['administrator', 'creator']:
                await status_msg.edit_text(
                    f"❌ البوت ليس مشرفاً في @{channel_username}\n"
                    "الرجاء رفع البوت مشرفاً ثم حاول مرة أخرى",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 إلغاء", callback_data="back_to_main")
                    ]])
                )
                return
            
            if not bot_member.can_delete_messages:
                await status_msg.edit_text(
                    "❌ البوت لا يملك صلاحية حذف الرسائل\n"
                    "الرجاء إعطاء البوت جميع الصلاحيات",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 إلغاء", callback_data="back_to_main")
                    ]])
                )
                return
            
            channel_data = ChannelData(
                id=chat.id,
                link=link,
                title=chat.title or channel_username,
                added_date=datetime.now(TIMEZONE),
                is_active=True
            )
            
            success, result_text = await db.add_channel(user_id, channel_data)
            
            db_user = await db.get_user(user_id)
            await status_msg.edit_text(
                result_text,
                reply_markup=Keyboards.main_menu(user_id, db_user.is_vip if db_user else False)
            )
            
        except TelegramError as e:
            logger.error(f"Error verifying channel: {e}")
            await status_msg.edit_text(
                "❌ حدث خطأ في التحقق من القناة\n"
                "تأكد من:\n"
                "• صحة رابط القناة\n"
                "• رفع البوت كمشرف في القناة\n"
                "• إعطاء البوت جميع الصلاحيات",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 إلغاء", callback_data="back_to_main")
                ]])
            )
        
        finally:
            context.user_data['awaiting_channel'] = False
    
    @staticmethod
    async def show_channels(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
        """عرض قائمة القنوات"""
        query = update.callback_query
        user_id = update.effective_user.id
        
        db_user = await db.get_user(user_id)
        if not db_user or not db_user.channels:
            await query.edit_message_text(
                "📭 لا توجد قنوات مضافة",
                reply_markup=Keyboards.main_menu(user_id, db_user.is_vip if db_user else False)
            )
            return
        
        channels = db_user.channels
        max_channels = MAX_VIP_CHANNELS if db_user.is_vip else MAX_FREE_CHANNELS
        
        text = f"📋 **قنواتك** ({len(channels)}/{max_channels}):\n\n"
        
        start = page * 5
        end = min(start + 5, len(channels))
        
        for i, channel in enumerate(channels[start:end], start + 1):
            text += f"{i}. **{channel.title}**\n"
            text += f"   الرابط: {channel.link}\n"
            text += f"   تاريخ الإضافة: {helpers.format_date(channel.added_date)}\n\n"
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=Keyboards.channels_menu(channels, page)
        )
    
    @staticmethod
    async def vip_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """قائمة VIP"""
        query = update.callback_query
        user_id = update.effective_user.id
        
        db_user = await db.get_user(user_id)
        is_vip = db_user and db_user.is_vip
        
        if is_vip:
            remaining = helpers.format_remaining_days(db_user.expiry_date)
            text = (
                f"🌟 **أنت مشترك VIP** 🌟\n\n"
                f"⏱ المتبقي: {remaining}\n"
                f"📊 القنوات: {len(db_user.channels)}/{MAX_VIP_CHANNELS}\n\n"
                f"شكراً لدعمك! 🙏"
            )
        else:
            text = (
                "✨ **مميزات VIP** ✨\n\n"
                f"• حتى **{MAX_VIP_CHANNELS}** قنوات\n"
                f"• مدة الاشتراك: **{VIP_DAYS}** يوم\n"
                "• دعم فني متميز\n\n"
                f"💰 السعر: **{VIP_PRICE}** نجمة\n\n"
                f"📞 للشراء، تواصل مع @{ADMIN_USERNAME}"
            )
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=Keyboards.vip_menu()
        )
    
    @staticmethod
    async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """لوحة تحكم المدير"""
        query = update.callback_query
        
        stats = await db.get_statistics()
        
        text = (
            "⚙️ **لوحة التحكم**\n\n"
            f"📊 إحصائيات سريعة:\n"
            f"👥 إجمالي المستخدمين: {stats['total_users']}\n"
            f"⭐ VIP: {stats['vip_users']}\n"
            f"✅ نشطين: {stats['active_users']}\n"
            f"📅 جديد اليوم: {stats['new_today']}\n\n"
            "اختر من القائمة:"
        )
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=Keyboards.admin_panel()
        )
    
    @staticmethod
    async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض إحصائيات مفصلة"""
        query = update.callback_query
        stats = await db.get_statistics()
        
        text = (
            "📊 **إحصائيات البوت**\n\n"
            f"👥 إجمالي المستخدمين: {stats['total_users']}\n"
            f"⭐ مستخدمين VIP: {stats['vip_users']}\n"
            f"✅ مستخدمين نشطين: {stats['active_users']}\n"
            f"❌ مستخدمين منتهيين: {stats['expired_users']}\n"
            f"🚫 محظورين: {stats['banned_users']}\n"
            f"📅 مستخدمين جدد اليوم: {stats['new_today']}\n"
            f"📢 إجمالي القنوات: {stats['total_channels']}"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    @staticmethod
    async def handle_price_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج تغيير السعر"""
        if not context.user_data.get('awaiting_price'):
            return
        
        message = update.message
        try:
            global VIP_PRICE
            new_price = int(message.text.strip())
            if new_price < 1:
                await message.reply_text("❌ السعر يجب أن يكون أكبر من 0")
                return
            
            VIP_PRICE = new_price
            
            await message.reply_text(
                f"✅ تم تغيير السعر إلى {new_price} نجمة",
                reply_markup=Keyboards.admin_panel()
            )
            
        except ValueError:
            await message.reply_text("❌ الرجاء إرسال رقم صحيح")
        finally:
            context.user_data['awaiting_price'] = False
    
    @staticmethod
    async def handle_activate_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج تفعيل VIP"""
        message = update.message
        user_id = update.effective_user.id
        
        if user_id != ADMIN_ID:
            return
        
        # استقبال ايدي المستخدم
        if context.user_data.get('awaiting_activate_user'):
            try:
                target_user_id = int(message.text.strip())
                context.user_data['activate_user_id'] = target_user_id
                context.user_data['awaiting_activate_user'] = False
                context.user_data['awaiting_activate_days'] = True
                
                await message.reply_text(
                    f"✅ تم استلام ايدي المستخدم: `{target_user_id}`\n\n"
                    "الآن أرسل **عدد الأيام** لتفعيل الاشتراك:\n"
                    "مثال: `30`",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ACTIVATE_VIP_WAITING_DAYS
                
            except ValueError:
                await message.reply_text("❌ ايدي غير صحيح! أرسل رقماً فقط")
                return
        
        # استقبال عدد الأيام
        if context.user_data.get('awaiting_activate_days'):
            try:
                days = int(message.text.strip())
                if days < 1:
                    await message.reply_text("❌ عدد الأيام يجب أن يكون أكبر من 0")
                    return
                
                target_user_id = context.user_data.get('activate_user_id')
                
                # تفعيل VIP
                success = await db.activate_vip(target_user_id, days)
                
                if success:
                    # إرسال إشعار للمستخدم المستهدف
                    try:
                        await context.bot.send_message(
                            target_user_id,
                            f"✅ **تم تفعيل اشتراك VIP لك!**\n\n"
                            f"📅 المدة: {days} يوم\n"
                            f"⭐ القنوات المسموحة: {MAX_VIP_CHANNELS}\n\n"
                            f"شكراً لدعمك! 🙏",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except:
                        pass
                    
                    await message.reply_text(
                        f"✅ **تم تفعيل VIP للمستخدم**\n\n"
                        f"👤 ايدي المستخدم: `{target_user_id}`\n"
                        f"📅 المدة: {days} يوم\n"
                        f"✅ تم إرسال إشعار للمستخدم",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=Keyboards.admin_panel()
                    )
                else:
                    await message.reply_text(
                        "❌ فشل في تفعيل VIP. المستخدم غير موجود؟",
                        reply_markup=Keyboards.admin_panel()
                    )
                
            except ValueError:
                await message.reply_text("❌ عدد الأيام غير صحيح! أرسل رقماً فقط")
            finally:
                context.user_data['awaiting_activate_days'] = False
                context.user_data['activate_user_id'] = None
    
    @staticmethod
    async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج الإذاعة"""
        if not context.user_data.get('awaiting_broadcast'):
            return
        
        message = update.message
        context.user_data['broadcast_message'] = message
        
        await message.reply_text(
            "📢 **معاينة الرسالة:**\n\n"
            f"{message.text if message.text else '[ميديا]'}\n\n"
            "هل أنت متأكد من إذاعتها للجميع؟",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=Keyboards.confirm_keyboard("broadcast")
        )
        
        context.user_data['awaiting_broadcast'] = False
        return BROADCAST_CONFIRM
    
    @staticmethod
    async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تأكيد الإذاعة"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "confirm_broadcast":
            await query.edit_message_text("📤 جاري الإذاعة... الرجاء الانتظار")
            
            users = await db.get_all_users()
            broadcast_message = context.user_data.get('broadcast_message')
            
            if not broadcast_message:
                await query.edit_message_text("❌ لا توجد رسالة")
                return
            
            stats = {'sent': 0, 'failed': 0, 'blocked': 0}
            
            status_msg = await query.edit_message_text(
                f"📤 جاري الإذاعة...\nتم الإرسال: {stats['sent']}"
            )
            
            for user in users:
                try:
                    if broadcast_message.text:
                        await context.bot.send_message(
                            user.user_id,
                            broadcast_message.text,
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await broadcast_message.copy(user.user_id)
                    
                    stats['sent'] += 1
                    
                except Exception as e:
                    if "blocked" in str(e).lower():
                        stats['blocked'] += 1
                    else:
                        stats['failed'] += 1
                
                if (stats['sent'] + stats['failed'] + stats['blocked']) % 10 == 0:
                    await status_msg.edit_text(
                        f"📤 جاري الإذاعة...\n"
                        f"تم الإرسال: {stats['sent']}\n"
                        f"فشل: {stats['failed']}\n"
                        f"محظور: {stats['blocked']}"
                    )
                
                await asyncio.sleep(0.05)
            
            result = (
                f"✅ **تمت الإذاعة**\n\n"
                f"تم الإرسال: {stats['sent']}\n"
                f"فشل: {stats['failed']}\n"
                f"محظور البوت: {stats['blocked']}"
            )
            
            await status_msg.edit_text(result, parse_mode=ParseMode.MARKDOWN)
            
        else:  # إلغاء
            await query.edit_message_text("✅ تم إلغاء الإذاعة")
        
        context.user_data.clear()
        await query.message.reply_text(
            "القائمة الرئيسية",
            reply_markup=Keyboards.admin_panel()
        )
    
    @staticmethod
    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إلغاء العملية الحالية"""
        user_id = update.effective_user.id
        
        context.user_data.clear()
        
        db_user = await db.get_user(user_id)
        
        await update.message.reply_text(
            "✅ تم إلغاء العملية",
            reply_markup=Keyboards.main_menu(user_id, db_user.is_vip if db_user else False)
        )
        
        return ConversationHandler.END

# ==================== معالج أحداث المجموعات ====================

class GroupHandlers:
    """معالج أحداث المجموعات"""
    
    @staticmethod
    async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج تغيير العضوية"""
        try:
            chat_member = update.chat_member
            chat = update.effective_chat
            
            if chat.type == ChatType.PRIVATE:
                return
            
            user = chat_member.new_chat_member.user
            
            users = await db.get_all_users()
            
            for db_user in users:
                for channel in db_user.channels:
                    if channel.id == chat.id:
                        settings = db_user.settings
                        
                        if db_user.expiry_date <= datetime.now(TIMEZONE):
                            continue
                        
                        # انضمام عضو جديد
                        if (chat_member.new_chat_member.status == 'member' and 
                            chat_member.old_chat_member.status in ['left', 'kicked']):
                            
                            if settings.ban_new_members:
                                try:
                                    await context.bot.ban_chat_member(chat.id, user.id)
                                    logger.info(f"Banned new member {user.id} from {chat.id}")
                                except Exception as e:
                                    logger.error(f"Error banning new member: {e}")
                            
                            if settings.ban_no_username and not user.username:
                                try:
                                    await context.bot.ban_chat_member(chat.id, user.id)
                                    logger.info(f"Banned no-username member {user.id}")
                                except Exception as e:
                                    logger.error(f"Error banning no-username: {e}")
                        
                        # مغادرة عضو
                        elif (chat_member.new_chat_member.status in ['left', 'kicked'] and 
                              chat_member.old_chat_member.status == 'member'):
                            
                            if settings.ban_leavers:
                                try:
                                    await context.bot.ban_chat_member(chat.id, user.id)
                                    logger.info(f"Banned leaver {user.id} from {chat.id}")
                                except Exception as e:
                                    logger.error(f"Error banning leaver: {e}")
                        
                        break
        
        except Exception as e:
            logger.error(f"Error in chat_member_handler: {e}")

# ==================== معالج الأخطاء ====================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأخطاء"""
    logger.error(f"Exception: {context.error}")
    
    try:
        if update and update.effective_chat:
            await context.bot.send_message(
                update.effective_chat.id,
                "❌ حدث خطأ. الرجاء المحاولة لاحقاً."
            )
    except:
        pass
    
    try:
        tb = traceback.format_exception(None, context.error, context.error.__traceback__)
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ **خطأ في البوت**\n\n{''.join(tb)[:3500]}",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        pass

# ==================== تهيئة البوت ====================

async def post_init(application: Application):
    """بعد تهيئة البوت"""
    await db.init_tables()
    logger.info("✅ Bot initialized")

def main():
    """تشغيل البوت"""
    
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    
    # أوامر أساسية
    application.add_handler(CommandHandler("start", CommandHandlers.start))
    application.add_handler(CommandHandler("cancel", CommandHandlers.cancel))
    
    # محادثة إضافة قناة
    add_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(CommandHandlers.add_channel_start, pattern="^add_channel$")],
        states={
            ADD_CHANNEL_WAITING_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, CommandHandlers.handle_channel_link)
            ],
        },
        fallbacks=[CommandHandler("cancel", CommandHandlers.cancel)],
        per_message=False
    )
    application.add_handler(add_channel_conv)
    
    # محادثة تغيير السعر
    change_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(
            lambda u, c: CommandHandlers.handle_callback(u, c) 
            if u.callback_query.data == "admin_change_price" else None,
            pattern="^admin_change_price$"
        )],
        states={
            CHANGE_PRICE_WAITING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, CommandHandlers.handle_price_change)
            ],
        },
        fallbacks=[CommandHandler("cancel", CommandHandlers.cancel)],
        per_message=False
    )
    application.add_handler(change_price_conv)
    
    # محادثة تفعيل VIP
    activate_vip_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(
            lambda u, c: CommandHandlers.handle_callback(u, c) 
            if u.callback_query.data == "admin_activate_vip" else None,
            pattern="^admin_activate_vip$"
        )],
        states={
            ACTIVATE_VIP_WAITING_USER_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, CommandHandlers.handle_activate_vip)
            ],
            ACTIVATE_VIP_WAITING_DAYS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, CommandHandlers.handle_activate_vip)
            ],
        },
        fallbacks=[CommandHandler("cancel", CommandHandlers.cancel)],
        per_message=False
    )
    application.add_handler(activate_vip_conv)
    
    # محادثة الإذاعة
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(
            lambda u, c: CommandHandlers.handle_callback(u, c) 
            if u.callback_query.data == "admin_broadcast" else None,
            pattern="^admin_broadcast$"
        )],
        states={
            BROADCAST_WAITING_MESSAGE: [
                MessageHandler(filters.ALL & ~filters.COMMAND, CommandHandlers.handle_broadcast)
            ],
            BROADCAST_CONFIRM: [
                CallbackQueryHandler(CommandHandlers.confirm_broadcast, pattern="^(confirm|cancel)_broadcast$")
            ],
        },
        fallbacks=[CommandHandler("cancel", CommandHandlers.cancel)],
        per_message=False
    )
    application.add_handler(broadcast_conv)
    
    # معالج الأزرار الرئيسي
    application.add_handler(CallbackQueryHandler(CommandHandlers.handle_callback))
    
    # معالج أحداث المجموعات
    application.add_handler(ChatMemberHandler(
        GroupHandlers.handle_chat_member, 
        ChatMemberHandler.CHAT_MEMBER
    ))
    
    # معالج الأخطاء
    application.add_error_handler(error_handler)
    
    # تشغيل البوت
    logger.info("🚀 Starting bot...")
    print("\n" + "="*50)
    print("✅ البوت يعمل بنجاح!")
    print(f"👤 المدير: @{ADMIN_USERNAME}")
    print(f"💰 سعر VIP: {VIP_PRICE} نجمة")
    print(f"📝 سجل الأحداث: bot.log")
    print("="*50 + "\n")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
