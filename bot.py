#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت تمويل متكامل لتليجرام
الإصدار: 1.0
المطور: System
"""

import os
import sys
import json
import asyncio
import logging
import sqlite3
import random
import string
import time
import shutil
import hashlib
import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any, Union
from pathlib import Path
from contextlib import contextmanager
from collections import defaultdict
from functools import wraps
import aiofiles
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import TelegramError, BadRequest, Forbidden
import pytz
from colorama import init, Fore, Back, Style

# تهيئة colorama
init(autoreset=True)

# ==================== الإعدادات الأساسية ====================

BOT_TOKEN = "8699966374:AAGCCGehxTQzGbEkBxIe7L3vecLPcvzGrHg"
ADMIN_IDS = [6615860762, 6130994941]  # معرفي المديرين

# مجلدات البوت
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
NUMBERS_DIR = DATA_DIR / "numbers"
BACKUP_DIR = DATA_DIR / "backup"
LOGS_DIR = BASE_DIR / "logs"

# إنشاء المجلدات المطلوبة
for dir_path in [DATA_DIR, NUMBERS_DIR, BACKUP_DIR, LOGS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# إعداد التسجيل (logging)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOGS_DIR / f"bot_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== إدارة قاعدة البيانات ====================

class DatabaseManager:
    """إدارة قاعدة البيانات بشكل آمن"""
    
    def __init__(self, db_path: str = "bot_database.db"):
        self.db_path = DATA_DIR / db_path
        self.init_database()
    
    def init_database(self):
        """إنشاء جداول قاعدة البيانات"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # جدول المستخدمين
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    points INTEGER DEFAULT 0,
                    referrals INTEGER DEFAULT 0,
                    joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_banned BOOLEAN DEFAULT 0,
                    is_admin BOOLEAN DEFAULT 0,
                    referrer_id INTEGER DEFAULT NULL,
                    total_funded INTEGER DEFAULT 0,
                    settings TEXT DEFAULT '{}'
                )
            ''')
            
            # جدول روابط الدعوة
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS referral_links (
                    user_id INTEGER PRIMARY KEY,
                    link_code TEXT UNIQUE,
                    clicks INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # جدول التمويلات
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS funding_requests (
                    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    chat_id TEXT,
                    chat_title TEXT,
                    members_count INTEGER,
                    cost_points INTEGER,
                    status TEXT DEFAULT 'pending',
                    added_count INTEGER DEFAULT 0,
                    remaining_count INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    chat_type TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # جدول أرقام التمويل
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS funding_numbers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone_number TEXT UNIQUE,
                    is_used BOOLEAN DEFAULT 0,
                    added_by INTEGER,
                    file_name TEXT,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    used_date TIMESTAMP,
                    used_in_request INTEGER,
                    FOREIGN KEY (added_by) REFERENCES users (user_id),
                    FOREIGN KEY (used_in_request) REFERENCES funding_requests (request_id)
                )
            ''')
            
            # جدول إعدادات البوت
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # جدول القنوات الإجبارية
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS force_channels (
                    channel_id TEXT PRIMARY KEY,
                    channel_username TEXT,
                    channel_title TEXT,
                    added_by INTEGER,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1
                )
            ''')
            
            # جدول المستخدمين المحظورين
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS banned_users (
                    user_id INTEGER PRIMARY KEY,
                    banned_by INTEGER,
                    reason TEXT,
                    banned_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    FOREIGN KEY (banned_by) REFERENCES users (user_id)
                )
            ''')
            
            # جدول سجل النقاط
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS points_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    action_type TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # جدول ملفات الأرقام
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS number_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_name TEXT,
                    file_path TEXT,
                    numbers_count INTEGER,
                    added_by INTEGER,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    FOREIGN KEY (added_by) REFERENCES users (user_id)
                )
            ''')
            
            # إدراج الإعدادات الافتراضية
            default_settings = [
                ('referral_reward', '10'),
                ('member_cost', '8'),
                ('welcome_message', '👋 مرحباً بك في بوت التمويل!\nنقاطك: {points}\nايديك: {user_id}\n@{username}'),
                ('support_username', 'support_bot'),
                ('channel_username', 'channel_username'),
                ('min_withdraw', '100'),
                ('max_daily_funding', '1000'),
                ('bot_status', 'active'),
                ('backup_time', '03:00'),
                ('auto_clean_days', '30')
            ]
            
            for key, value in default_settings:
                cursor.execute('''
                    INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)
                ''', (key, value))
            
            conn.commit()
    
    @contextmanager
    def get_connection(self):
        """الحصول على اتصال بقاعدة البيانات"""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()
    
    def execute_query(self, query: str, params: tuple = (), fetch_one: bool = False):
        """تنفيذ استعلام قاعدة بيانات"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            if fetch_one:
                return cursor.fetchone()
            return cursor.fetchall()
    
    def execute_insert(self, query: str, params: tuple = ()) -> int:
        """تنفيذ إدراج والحصول على آخر ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid

# إنشاء كائن قاعدة البيانات
db = DatabaseManager()

# ==================== الإحصائيات والمراقبة ====================

class BotStats:
    """إحصائيات البوت"""
    
    @staticmethod
    def get_total_users() -> int:
        """عدد المستخدمين الكلي"""
        result = db.execute_query("SELECT COUNT(*) as count FROM users", fetch_one=True)
        return result['count'] if result else 0
    
    @staticmethod
    def get_active_users(days: int = 7) -> int:
        """عدد المستخدمين النشطين خلال آخر X أيام"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        result = db.execute_query(
            "SELECT COUNT(*) as count FROM users WHERE last_active > ?",
            (cutoff,),
            fetch_one=True
        )
        return result['count'] if result else 0
    
    @staticmethod
    def get_banned_users() -> int:
        """عدد المستخدمين المحظورين"""
        result = db.execute_query("SELECT COUNT(*) as count FROM banned_users", fetch_one=True)
        return result['count'] if result else 0
    
    @staticmethod
    def get_total_points() -> int:
        """مجموع النقاط في النظام"""
        result = db.execute_query("SELECT SUM(points) as total FROM users", fetch_one=True)
        return result['total'] if result and result['total'] else 0
    
    @staticmethod
    def get_total_funding() -> int:
        """عدد التمويلات المنفذة"""
        result = db.execute_query(
            "SELECT COUNT(*) as count FROM funding_requests WHERE status = 'completed'",
            fetch_one=True
        )
        return result['count'] if result else 0
    
    @staticmethod
    def get_total_members_added() -> int:
        """عدد الأعضاء المضافين"""
        result = db.execute_query(
            "SELECT SUM(added_count) as total FROM funding_requests WHERE status = 'completed'",
            fetch_one=True
        )
        return result['total'] if result and result['total'] else 0
    
    @staticmethod
    def get_available_numbers() -> int:
        """عدد الأرقام المتاحة للتمويل"""
        result = db.execute_query(
            "SELECT COUNT(*) as count FROM funding_numbers WHERE is_used = 0",
            fetch_one=True
        )
        return result['count'] if result else 0
    
    @staticmethod
    def get_total_numbers() -> int:
        """إجمالي الأرقام المضافة"""
        result = db.execute_query("SELECT COUNT(*) as count FROM funding_numbers", fetch_one=True)
        return result['count'] if result else 0
    
    @staticmethod
    def get_top_users(limit: int = 10) -> List[Dict]:
        """أفضل المستخدمين من حيث النقاط"""
        results = db.execute_query("""
            SELECT user_id, username, points, referrals, total_funded 
            FROM users 
            WHERE is_banned = 0 
            ORDER BY points DESC 
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in results]

stats = BotStats()

# ==================== الدوال المساعدة ====================

class Helpers:
    """دوال مساعدة متنوعة"""
    
    @staticmethod
    def generate_code(length: int = 8) -> str:
        """توليد كود عشوائي"""
        chars = string.ascii_letters + string.digits
        return ''.join(random.choice(chars) for _ in range(length))
    
    @staticmethod
    def format_number(num: int) -> str:
        """تنسيق الأرقام"""
        if num >= 1_000_000:
            return f"{num/1_000_000:.1f}M"
        elif num >= 1_000:
            return f"{num/1_000:.1f}K"
        return str(num)
    
    @staticmethod
    def extract_username(text: str) -> Optional[str]:
        """استخراج اسم المستخدم من النص"""
        match = re.search(r'@(\w+)', text)
        return match.group(1) if match else None
    
    @staticmethod
    def extract_channel_id(text: str) -> Optional[str]:
        """استخراج معرف القناة"""
        # للروابط
        if 't.me/' in text:
            parts = text.split('t.me/')
            if len(parts) > 1:
                return parts[1].split('/')[0]
        # للمعرفات
        elif text.startswith('@'):
            return text[1:]
        # للأرقام
        elif text.startswith('-100'):
            return text
        return None
    
    @staticmethod
    async def check_membership(user_id: int, channel_id: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """التحقق من عضوية المستخدم في قناة"""
        try:
            member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
        except:
            return False
    
    @staticmethod
    async def safe_send_message(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE, **kwargs) -> bool:
        """إرسال رسالة بشكل آمن"""
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
            return True
        except Exception as e:
            logger.error(f"Error sending message to {chat_id}: {e}")
            return False
    
    @staticmethod
    def parse_txt_file(file_content: str) -> List[str]:
        """تحليل ملف txt واستخراج الأرقام"""
        lines = file_content.strip().split('\n')
        numbers = []
        for line in lines:
            # تنظيف الرقم من المسافات والرموز غير المرغوب فيها
            num = re.sub(r'[^\d+]', '', line.strip())
            if num and len(num) >= 10:  # رقم صحيح
                numbers.append(num)
        return numbers
    
    @staticmethod
    def calculate_cost(members_count: int, cost_per_member: int) -> int:
        """حساب تكلفة التمويل"""
        return members_count * cost_per_member
    
    @staticmethod
    def create_backup() -> str:
        """إنشاء نسخة احتياطية من قاعدة البيانات"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = BACKUP_DIR / f"backup_{timestamp}.db"
        shutil.copy2(db.db_path, backup_file)
        return str(backup_file)

helpers = Helpers()

# ==================== إدارة المستخدمين ====================

class UserManager:
    """إدارة المستخدمين"""
    
    @staticmethod
    async def get_or_create_user(user: Update.effective_user) -> Dict:
        """الحصول على المستخدم أو إنشائه"""
        user_id = user.id
        username = user.username or ""
        first_name = user.first_name or ""
        last_name = user.last_name or ""
        
        # التحقق من وجود المستخدم
        existing = db.execute_query(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
            fetch_one=True
        )
        
        if existing:
            # تحديث آخر نشاط
            db.execute_query(
                "UPDATE users SET last_active = CURRENT_TIMESTAMP, username = ?, first_name = ?, last_name = ? WHERE user_id = ?",
                (username, first_name, last_name, user_id)
            )
            return dict(existing)
        else:
            # إنشاء مستخدم جديد
            db.execute_query("""
                INSERT INTO users (user_id, username, first_name, last_name, points, joined_date)
                VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
            """, (user_id, username, first_name, last_name))
            
            # إنشاء رابط دعوة
            code = helpers.generate_code(10)
            db.execute_query(
                "INSERT INTO referral_links (user_id, link_code) VALUES (?, ?)",
                (user_id, code)
            )
            
            new_user = db.execute_query(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,),
                fetch_one=True
            )
            return dict(new_user)
    
    @staticmethod
    def get_user(user_id: int) -> Optional[Dict]:
        """الحصول على معلومات المستخدم"""
        result = db.execute_query(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
            fetch_one=True
        )
        return dict(result) if result else None
    
    @staticmethod
    def update_points(user_id: int, amount: int, action: str, description: str = "") -> bool:
        """تحديث نقاط المستخدم"""
        user = UserManager.get_user(user_id)
        if not user:
            return False
        
        new_points = user['points'] + amount
        if new_points < 0:
            return False
        
        db.execute_query(
            "UPDATE users SET points = ? WHERE user_id = ?",
            (new_points, user_id)
        )
        
        # تسجيل الحركة
        db.execute_query("""
            INSERT INTO points_history (user_id, amount, action_type, description)
            VALUES (?, ?, ?, ?)
        """, (user_id, amount, action, description))
        
        return True
    
    @staticmethod
    def add_referral(user_id: int, referrer_id: int) -> bool:
        """إضافة إحالة جديدة"""
        # تحديث عدد الإحالات للمحيل
        db.execute_query(
            "UPDATE users SET referrals = referrals + 1 WHERE user_id = ?",
            (referrer_id,)
        )
        
        # تحديث المحال
        db.execute_query(
            "UPDATE users SET referrer_id = ? WHERE user_id = ?",
            (referrer_id, user_id)
        )
        
        return True
    
    @staticmethod
    def ban_user(user_id: int, admin_id: int, reason: str = "") -> bool:
        """حظر مستخدم"""
        if user_id in ADMIN_IDS:
            return False
        
        db.execute_query(
            "UPDATE users SET is_banned = 1 WHERE user_id = ?",
            (user_id,)
        )
        
        db.execute_query("""
            INSERT OR REPLACE INTO banned_users (user_id, banned_by, reason)
            VALUES (?, ?, ?)
        """, (user_id, admin_id, reason))
        
        return True
    
    @staticmethod
    def unban_user(user_id: int) -> bool:
        """رفع الحظر عن مستخدم"""
        db.execute_query(
            "UPDATE users SET is_banned = 0 WHERE user_id = ?",
            (user_id,)
        )
        
        db.execute_query(
            "DELETE FROM banned_users WHERE user_id = ?",
            (user_id,)
        )
        
        return True
    
    @staticmethod
    def is_banned(user_id: int) -> bool:
        """التحقق من حظر المستخدم"""
        result = db.execute_query(
            "SELECT is_banned FROM users WHERE user_id = ?",
            (user_id,),
            fetch_one=True
        )
        return bool(result and result['is_banned'])

user_manager = UserManager()

# ==================== إعدادات البوت ====================

class BotSettings:
    """إدارة إعدادات البوت"""
    
    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        """الحصول على قيمة إعداد"""
        result = db.execute_query(
            "SELECT value FROM bot_settings WHERE key = ?",
            (key,),
            fetch_one=True
        )
        return result['value'] if result else default
    
    @staticmethod
    def set(key: str, value: str) -> bool:
        """تعيين قيمة إعداد"""
        db.execute_query("""
            INSERT OR REPLACE INTO bot_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (key, value))
        return True
    
    @staticmethod
    def get_welcome_message(user_id: int, username: str, points: int) -> str:
        """الحصول على رسالة الترحيب المنسقة"""
        template = BotSettings.get('welcome_message', 
            "👋 مرحباً بك في بوت التمويل!\nنقاطك: {points}\nايديك: {user_id}\n@{username}")
        return template.format(user_id=user_id, username=username, points=points)
    
    @staticmethod
    def get_referral_reward() -> int:
        """مكافأة الدعوة"""
        return int(BotSettings.get('referral_reward', '10'))
    
    @staticmethod
    def get_member_cost() -> int:
        """تكلفة العضو الواحد"""
        return int(BotSettings.get('member_cost', '8'))
    
    @staticmethod
    def get_support_username() -> str:
        """اسم مستخدم الدعم"""
        return BotSettings.get('support_username', 'support_bot')
    
    @staticmethod
    def get_channel_username() -> str:
        """اسم مستخدم القناة"""
        return BotSettings.get('channel_username', 'channel_username')

settings = BotSettings()

# ==================== القنوات الإجبارية ====================

class ForceChannelManager:
    """إدارة القنوات الإجبارية"""
    
    @staticmethod
    def add_channel(channel_id: str, channel_username: str, channel_title: str, added_by: int) -> bool:
        """إضافة قناة إجبارية"""
        try:
            db.execute_query("""
                INSERT OR REPLACE INTO force_channels (channel_id, channel_username, channel_title, added_by)
                VALUES (?, ?, ?, ?)
            """, (channel_id, channel_username, channel_title, added_by))
            return True
        except:
            return False
    
    @staticmethod
    def remove_channel(channel_id: str) -> bool:
        """حذف قناة إجبارية"""
        db.execute_query(
            "DELETE FROM force_channels WHERE channel_id = ?",
            (channel_id,)
        )
        return True
    
    @staticmethod
    def get_all_channels() -> List[Dict]:
        """الحصول على جميع القنوات الإجبارية النشطة"""
        results = db.execute_query(
            "SELECT * FROM force_channels WHERE is_active = 1 ORDER BY added_date DESC"
        )
        return [dict(row) for row in results]
    
    @staticmethod
    async def check_all_memberships(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, List[Dict]]:
        """التحقق من عضوية المستخدم في جميع القنوات"""
        channels = ForceChannelManager.get_all_channels()
        not_joined = []
        
        for channel in channels:
            is_member = await helpers.check_membership(user_id, channel['channel_id'], context)
            if not is_member:
                not_joined.append(channel)
        
        return len(not_joined) == 0, not_joined
    
    @staticmethod
    def get_channels_keyboard() -> InlineKeyboardMarkup:
        """الحصول على لوحة مفاتيح القنوات"""
        channels = ForceChannelManager.get_all_channels()
        keyboard = []
        
        for channel in channels:
            if channel['channel_username']:
                url = f"https://t.me/{channel['channel_username']}"
                keyboard.append([InlineKeyboardButton(f"📢 {channel['channel_title']}", url=url)])
        
        keyboard.append([InlineKeyboardButton("✅ تم الاشتراك", callback_data="check_subscription")])
        
        return InlineKeyboardMarkup(keyboard)

force_manager = ForceChannelManager()

# ==================== إدارة التمويل ====================

class FundingManager:
    """إدارة عمليات التمويل"""
    
    def __init__(self):
        self.active_funding = {}  # تخزين عمليات التمويل النشطة مؤقتاً
        self.user_requests = defaultdict(dict)  # تخزين طلبات المستخدمين المؤقتة
    
    async def start_funding(self, user_id: int, members_count: int, chat_link: str, context: ContextTypes.DEFAULT_TYPE):
        """بدء عملية تمويل جديدة"""
        try:
            # التحقق من صحة الرابط
            chat_info = await self.extract_chat_info(chat_link, context)
            if not chat_info:
                await helpers.safe_send_message(
                    user_id,
                    "❌ الرابط غير صحيح. تأكد من أن البوت مشرف في القناة وأن الرابط صحيح.",
                    context
                )
                return False
            
            # حساب التكلفة
            cost = helpers.calculate_cost(members_count, settings.get_member_cost())
            
            # التحقق من رصيد المستخدم
            user = user_manager.get_user(user_id)
            if user['points'] < cost:
                await helpers.safe_send_message(
                    user_id,
                    f"❌ رصيدك غير كافٍ!\n"
                    f"المطلوب: {cost} نقطة\n"
                    f"رصيدك: {user['points']} نقطة",
                    context
                )
                return False
            
            # التحقق من توفر أرقام كافية
            available = stats.get_available_numbers()
            if available < members_count:
                await helpers.safe_send_message(
                    user_id,
                    f"❌ لا يوجد عدد كافٍ من الأرقام المتاحة!\n"
                    f"المتاح: {available}\n"
                    f"المطلوب: {members_count}",
                    context
                )
                return False
            
            # خصم النقاط
            user_manager.update_points(user_id, -cost, "funding", f"تمويل {members_count} عضو")
            
            # إنشاء طلب تمويل
            request_id = db.execute_insert("""
                INSERT INTO funding_requests 
                (user_id, chat_id, chat_title, members_count, cost_points, remaining_count, chat_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                chat_info['chat_id'],
                chat_info['title'],
                members_count,
                cost,
                members_count,
                chat_info['type']
            ))
            
            # بدء عملية التمويل
            asyncio.create_task(self.process_funding(request_id, user_id, chat_info, members_count, context))
            
            # إشعار المستخدم
            await helpers.safe_send_message(
                user_id,
                f"✅ تم بدء عملية التمويل بنجاح!\n"
                f"📊 عدد الأعضاء: {members_count}\n"
                f"💰 التكلفة: {cost} نقطة\n"
                f"⏳ سيتم إعلامك عند إضافة كل عضو.",
                context
            )
            
            # إشعار المشرفين
            await self.notify_admins_new_funding(request_id, user_id, chat_info, members_count, cost, context)
            
            return True
            
        except Exception as e:
            logger.error(f"Error in start_funding: {e}")
            await helpers.safe_send_message(
                user_id,
                "❌ حدث خطأ أثناء بدء عملية التمويل. يرجى المحاولة لاحقاً.",
                context
            )
            return False
    
    async def extract_chat_info(self, link: str, context: ContextTypes.DEFAULT_TYPE) -> Optional[Dict]:
        """استخراج معلومات القناة/المجموعة من الرابط"""
        try:
            chat_username = helpers.extract_channel_id(link)
            if not chat_username:
                return None
            
            # محاولة الحصول على معلومات القناة
            try:
                chat = await context.bot.get_chat(chat_username)
            except:
                # محاولة كـ @username
                if not chat_username.startswith('@'):
                    chat_username = f"@{chat_username}"
                try:
                    chat = await context.bot.get_chat(chat_username)
                except:
                    return None
            
            return {
                'chat_id': str(chat.id),
                'username': chat.username or "",
                'title': chat.title or "Unknown",
                'type': chat.type
            }
        except Exception as e:
            logger.error(f"Error extracting chat info: {e}")
            return None
    
    async def process_funding(self, request_id: int, user_id: int, chat_info: Dict, 
                            total_members: int, context: ContextTypes.DEFAULT_TYPE):
        """معالجة عملية التمويل (إضافة الأعضاء)"""
        try:
            added = 0
            chat_id = chat_info['chat_id']
            
            while added < total_members:
                # الحصول على رقم غير مستخدم
                number = self.get_unused_number(request_id)
                if not number:
                    # لا يوجد أرقام كافية
                    await helpers.safe_send_message(
                        user_id,
                        f"⚠️ توقف التمويل: نفذت الأرقام المتاحة!\n"
                        f"تم إضافة {added} من أصل {total_members} عضو.",
                        context
                    )
                    break
                
                # محاولة إضافة العضو
                success = await self.add_member_to_chat(chat_id, number['phone_number'], context)
                
                if success:
                    added += 1
                    
                    # تحديث حالة الرقم
                    db.execute_query("""
                        UPDATE funding_numbers 
                        SET is_used = 1, used_date = CURRENT_TIMESTAMP, used_in_request = ?
                        WHERE id = ?
                    """, (request_id, number['id']))
                    
                    # تحديث طلب التمويل
                    db.execute_query("""
                        UPDATE funding_requests 
                        SET added_count = ?, remaining_count = ?
                        WHERE request_id = ?
                    """, (added, total_members - added, request_id))
                    
                    # إرسال إشعار كل 5 أعضاء
                    if added % 5 == 0 or added == total_members:
                        await helpers.safe_send_message(
                            user_id,
                            f"📊 تقدم التمويل:\n"
                            f"تم إضافة: {added}\n"
                            f"المتبقي: {total_members - added}",
                            context
                        )
                
                # تأخير لتجنب سبام
                await asyncio.sleep(random.uniform(2, 5))
            
            # اكتمال التمويل
            if added >= total_members:
                db.execute_query("""
                    UPDATE funding_requests 
                    SET status = 'completed', completed_at = CURRENT_TIMESTAMP
                    WHERE request_id = ?
                """, (request_id,))
                
                await helpers.safe_send_message(
                    user_id,
                    f"✅ تم اكتمال تمويل قناتك بنجاح!\n"
                    f"إجمالي الأعضاء المضافين: {added}",
                    context
                )
            
            # تحديث إحصائيات المستخدم
            db.execute_query("""
                UPDATE users 
                SET total_funded = total_funded + ? 
                WHERE user_id = ?
            """, (added, user_id))
            
        except Exception as e:
            logger.error(f"Error in process_funding: {e}")
            await helpers.safe_send_message(
                user_id,
                "❌ حدث خطأ أثناء عملية التمويل. يرجى التواصل مع الدعم الفني.",
                context
            )
    
    def get_unused_number(self, request_id: int) -> Optional[Dict]:
        """الحصول على رقم غير مستخدم"""
        result = db.execute_query("""
            SELECT id, phone_number FROM funding_numbers 
            WHERE is_used = 0 
            ORDER BY id ASC 
            LIMIT 1
        """, fetch_one=True)
        
        return dict(result) if result else None
    
    async def add_member_to_chat(self, chat_id: str, phone_number: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """إضافة عضو إلى القناة/المجموعة"""
        try:
            # هذه محاكاة لإضافة العضو - في الواقع تحتاج إلى استخدام API خاص
            # أو استخدام حساب تليجرام فعلي
            logger.info(f"Adding {phone_number} to {chat_id}")
            
            # محاكاة نجاح العملية
            await asyncio.sleep(1)
            return True
            
        except Exception as e:
            logger.error(f"Error adding member: {e}")
            return False
    
    async def notify_admins_new_funding(self, request_id: int, user_id: int, chat_info: Dict,
                                      members: int, cost: int, context: ContextTypes.DEFAULT_TYPE):
        """إشعار المشرفين بطلب تمويل جديد"""
        user = user_manager.get_user(user_id)
        
        text = (
            f"🔔 طلب تمويل جديد!\n\n"
            f"👤 المستخدم: {user['first_name']} (@{user['username']})\n"
            f"🆔 الايدي: {user_id}\n"
            f"📊 القناة: {chat_info['title']}\n"
            f"🔗 الرابط: @{chat_info['username'] if chat_info['username'] else 'خاص'}\n"
            f"👥 عدد الأعضاء: {members}\n"
            f"💰 التكلفة: {cost} نقطة\n"
            f"🆔 رقم الطلب: {request_id}\n\n"
            f"اختر إجراء:"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ قبول", callback_data=f"approve_fund_{request_id}"),
                InlineKeyboardButton("❌ رفض", callback_data=f"reject_fund_{request_id}")
            ],
            [InlineKeyboardButton("🚫 حظر المستخدم", callback_data=f"ban_user_{user_id}")]
        ]
        
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id,
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except:
                pass
    
    def get_user_funding(self, user_id: int) -> List[Dict]:
        """الحصول على تمويلات المستخدم"""
        results = db.execute_query("""
            SELECT * FROM funding_requests 
            WHERE user_id = ? 
            ORDER BY created_at DESC
        """, (user_id,))
        return [dict(row) for row in results]
    
    def cancel_funding(self, request_id: int) -> bool:
        """إلغاء طلب تمويل"""
        db.execute_query("""
            UPDATE funding_requests 
            SET status = 'cancelled' 
            WHERE request_id = ?
        """, (request_id,))
        return True

funding_manager = FundingManager()

# ==================== إدارة ملفات الأرقام ====================

class NumberFileManager:
    """إدارة ملفات الأرقام"""
    
    @staticmethod
    async def process_numbers_file(file_content: str, file_name: str, admin_id: int) -> Tuple[bool, int, List[str]]:
        """معالجة ملف الأرقام وإضافته إلى قاعدة البيانات"""
        numbers = helpers.parse_txt_file(file_content)
        
        if not numbers:
            return False, 0, []
        
        # حفظ الملف
        file_path = NUMBERS_DIR / file_name
        async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
            await f.write(file_content)
        
        # تسجيل الملف
        file_id = db.execute_insert("""
            INSERT INTO number_files (file_name, file_path, numbers_count, added_by)
            VALUES (?, ?, ?, ?)
        """, (file_name, str(file_path), len(numbers), admin_id))
        
        # إضافة الأرقام
        added_numbers = []
        for number in numbers:
            try:
                db.execute_query("""
                    INSERT OR IGNORE INTO funding_numbers (phone_number, added_by, file_name)
                    VALUES (?, ?, ?)
                """, (number, admin_id, file_name))
                added_numbers.append(number)
            except:
                pass
        
        return True, len(added_numbers), numbers
    
    @staticmethod
    def get_all_files() -> List[Dict]:
        """الحصول على جميع الملفات"""
        results = db.execute_query("""
            SELECT * FROM number_files 
            ORDER BY added_date DESC
        """)
        return [dict(row) for row in results]
    
    @staticmethod
    def delete_file(file_id: int) -> bool:
        """حذف ملف وأرقامه"""
        # الحصول على معلومات الملف
        file_info = db.execute_query(
            "SELECT * FROM number_files WHERE id = ?",
            (file_id,),
            fetch_one=True
        )
        
        if not file_info:
            return False
        
        # حذف الأرقام المرتبطة بالملف
        db.execute_query(
            "DELETE FROM funding_numbers WHERE file_name = ?",
            (file_info['file_name'],)
        )
        
        # حذف سجل الملف
        db.execute_query(
            "DELETE FROM number_files WHERE id = ?",
            (file_id,)
        )
        
        # حذف الملف الفعلي
        try:
            os.remove(file_info['file_path'])
        except:
            pass
        
        return True
    
    @staticmethod
    def get_file_stats() -> Dict:
        """إحصائيات الملفات"""
        total_files = db.execute_query(
            "SELECT COUNT(*) as count FROM number_files",
            fetch_one=True
        )
        
        total_numbers = db.execute_query(
            "SELECT COUNT(*) as count FROM funding_numbers",
            fetch_one=True
        )
        
        used_numbers = db.execute_query(
            "SELECT COUNT(*) as count FROM funding_numbers WHERE is_used = 1",
            fetch_one=True
        )
        
        return {
            'total_files': total_files['count'] if total_files else 0,
            'total_numbers': total_numbers['count'] if total_numbers else 0,
            'used_numbers': used_numbers['count'] if used_numbers else 0,
            'available': (total_numbers['count'] if total_numbers else 0) - (used_numbers['count'] if used_numbers else 0)
        }

file_manager = NumberFileManager()

# ==================== معالج الإحالات ====================

class ReferralHandler:
    """معالج روابط الإحالة"""
    
    @staticmethod
    async def process_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالجة الدخول عبر رابط إحالة"""
        try:
            args = context.args
            if not args:
                return
            
            referral_code = args[0]
            user_id = update.effective_user.id
            
            # البحث عن صاحب الرابط
            referrer = db.execute_query(
                "SELECT user_id FROM referral_links WHERE link_code = ?",
                (referral_code,),
                fetch_one=True
            )
            
            if not referrer or referrer['user_id'] == user_id:
                return
            
            # التحقق من أن المستخدم ليس مسجلاً مسبقاً
            existing_user = db.execute_query(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,),
                fetch_one=True
            )
            
            if not existing_user:
                # المستخدم جديد - تسجيله تحت المحيل
                context.user_data['referrer'] = referrer['user_id']
                
                # تخزين مؤقت للمحيل
                temp_data = db.execute_query(
                    "SELECT value FROM bot_settings WHERE key = 'temp_referrals'",
                    fetch_one=True
                )
                
                temp_refs = json.loads(temp_data['value']) if temp_data and temp_data['value'] else {}
                temp_refs[str(user_id)] = referrer['user_id']
                
                settings.set('temp_referrals', json.dumps(temp_refs))
                
        except Exception as e:
            logger.error(f"Error processing referral: {e}")
    
    @staticmethod
    def apply_referral_if_exists(user_id: int):
        """تطبيق الإحالة إذا كانت موجودة"""
        try:
            temp_data = settings.get('temp_referrals', '{}')
            temp_refs = json.loads(temp_data)
            
            if str(user_id) in temp_refs:
                referrer_id = temp_refs[str(user_id)]
                
                # إضافة الإحالة
                user_manager.add_referral(user_id, referrer_id)
                
                # إضافة مكافأة للمحيل
                reward = settings.get_referral_reward()
                user_manager.update_points(referrer_id, reward, "referral", f"مكافأة دعوة مستخدم جديد")
                
                # حذف من المؤقت
                del temp_refs[str(user_id)]
                settings.set('temp_referrals', json.dumps(temp_refs))
                
                return True
        except Exception as e:
            logger.error(f"Error applying referral: {e}")
        
        return False
    
    @staticmethod
    def get_referral_link(user_id: int) -> str:
        """الحصول على رابط إحالة المستخدم"""
        result = db.execute_query(
            "SELECT link_code FROM referral_links WHERE user_id = ?",
            (user_id,),
            fetch_one=True
        )
        
        if result:
            return f"https://t.me/{(context.bot.username)}?start={result['link_code']}"
        
        # إنشاء رابط جديد
        code = helpers.generate_code(10)
        db.execute_query(
            "INSERT OR REPLACE INTO referral_links (user_id, link_code) VALUES (?, ?)",
            (user_id, code)
        )
        
        return f"https://t.me/{(context.bot.username)}?start={code}"

referral_handler = ReferralHandler()

# ==================== حالات المحادثة ====================

# حالات المحادثة
(FUNDING_MEMBERS, FUNDING_LINK, ADMIN_AMOUNT, ADMIN_USER_ID, 
 ADMIN_FILE, ADMIN_CHANNEL, ADMIN_SUPPORT, ADMIN_REWARD, 
 ADMIN_COST, ADMIN_FORCE_CHANNEL, ADMIN_BAN_REASON) = range(11)

# ==================== دوال التحقق من العضوية ====================

async def check_force_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """التحقق من الاشتراك في القنوات الإجبارية"""
    user_id = update.effective_user.id
    
    # المشرفون مستثنون
    if user_id in ADMIN_IDS:
        return True
    
    is_subscribed, not_joined = await force_manager.check_all_memberships(user_id, context)
    
    if not is_subscribed:
        text = "🚫 للوصول إلى البوت، يجب الاشتراك في القنوات التالية أولاً:\n\n"
        keyboard = force_manager.get_channels_keyboard()
        
        await update.message.reply_text(text, reply_markup=keyboard)
        return False
    
    return True

# ==================== ديكوراتور التحقق ====================

def require_subscription(func):
    """ديكوراتور للتحقق من الاشتراك الإجباري"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if await check_force_subscription(update, context):
            return await func(update, context, *args, **kwargs)
        return ConversationHandler.END
    return wrapper

def admin_only(func):
    """ديكوراتور للتحقق من صلاحيات المشرف"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id in ADMIN_IDS:
            return await func(update, context, *args, **kwargs)
        else:
            await update.message.reply_text("⛔ هذه الخاصية متاحة فقط للمشرفين.")
            return ConversationHandler.END
    return wrapper

def not_banned(func):
    """ديكوراتور للتحقق من عدم حظر المستخدم"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_manager.is_banned(user_id):
            await update.message.reply_text("🚫 تم حظرك من استخدام البوت.")
            return ConversationHandler.END
        return await func(update, context, *args, **kwargs)
    return wrapper

# ==================== أوامر المستخدم العامة ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج أمر /start"""
    user = update.effective_user
    
    # معالجة الإحالة إذا وجدت
    await referral_handler.process_referral(update, context)
    
    # الحصول على المستخدم أو إنشائه
    user_data = await user_manager.get_or_create_user(user)
    
    # تطبيق الإحالة إذا كانت موجودة
    referral_handler.apply_referral_if_exists(user.id)
    
    # التحقق من العضوية الإجبارية
    is_subscribed, not_joined = await force_manager.check_all_memberships(user.id, context)
    
    if not is_subscribed and user.id not in ADMIN_IDS:
        text = "🚫 للوصول إلى البوت، يجب الاشتراك في القنوات التالية أولاً:\n\n"
        keyboard = force_manager.get_channels_keyboard()
        await update.message.reply_text(text, reply_markup=keyboard)
        return
    
    # عرض واجهة المستخدم الرئيسية
    welcome_text = settings.get_welcome_message(user.id, user.username or "لا يوجد", user_data['points'])
    
    # لوحة المفاتيح الرئيسية
    keyboard = [
        [InlineKeyboardButton("💰 تجميع النقاط", callback_data="earn_points")],
        [InlineKeyboardButton("🚀 تمويل مشتركين", callback_data="start_funding")],
        [InlineKeyboardButton("📊 تمويلاتي", callback_data="my_funding")],
        [InlineKeyboardButton("📈 احصائياتي", callback_data="my_stats")],
        [InlineKeyboardButton("🆘 الدعم الفني", url=f"https://t.me/{settings.get_support_username()}")],
        [InlineKeyboardButton("📢 قناة البوت", url=f"https://t.me/{settings.get_channel_username()}")]
    ]
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج الأزرار"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # التحقق من الحظر
    if user_manager.is_banned(user_id) and user_id not in ADMIN_IDS:
        await query.edit_message_text("🚫 تم حظرك من استخدام البوت.")
        return
    
    # معالجة الأزرار المختلفة
    if data == "earn_points":
        await show_earn_points(update, context)
    
    elif data == "start_funding":
        await start_funding_cmd(update, context)
    
    elif data == "my_funding":
        await show_my_funding(update, context)
    
    elif data == "my_stats":
        await show_my_stats(update, context)
    
    elif data == "check_subscription":
        await check_subscription_callback(update, context)
    
    elif data.startswith("approve_fund_"):
        if user_id in ADMIN_IDS:
            request_id = int(data.split("_")[2])
            await approve_funding(update, context, request_id)
    
    elif data.startswith("reject_fund_"):
        if user_id in ADMIN_IDS:
            request_id = int(data.split("_")[2])
            await reject_funding(update, context, request_id)
    
    elif data.startswith("ban_user_"):
        if user_id in ADMIN_IDS:
            target_id = int(data.split("_")[2])
            await ban_user_from_callback(update, context, target_id)

async def show_earn_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض واجهة تجميع النقاط"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # الحصول على رابط الدعوة
    link = referral_handler.get_referral_link(user_id)
    
    # إحصائيات الدعوات
    user = user_manager.get_user(user_id)
    referrals = user['referrals'] if user else 0
    reward = settings.get_referral_reward()
    
    text = (
        "💰 **تجميع النقاط**\n\n"
        "شارك الرابط التالي مع أصدقائك، كل مستخدم جديد يسجل عبر رابطك ستحصل على مكافأة فورية!\n\n"
        f"🔗 **رابط الدعوة الخاص بك:**\n"
        f"`{link}`\n\n"
        f"👥 عدد من دعوتهم: **{referrals}** مستخدم\n"
        f"🎁 المكافأة لكل دعوة: **{reward}** نقطة\n\n"
        "📌 يمكنك أيضاً شحن رصيدك عن طريق التواصل مع الدعم الفني."
    )
    
    keyboard = [
        [InlineKeyboardButton("🔙 العودة", callback_data="back_to_main")],
        [InlineKeyboardButton("🆘 الدعم الفني", url=f"https://t.me/{settings.get_support_username()}")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_funding_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية تمويل جديدة"""
    query = update.callback_query
    
    # التحقق من توفر أرقام
    available = stats.get_available_numbers()
    if available == 0:
        await query.edit_message_text(
            "❌ عذراً، لا توجد أرقام متاحة للتمويل حالياً.\n"
            "يرجى المحاولة لاحقاً أو التواصل مع الدعم الفني.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 العودة", callback_data="back_to_main")
            ]])
        )
        return
    
    # سعر العضو
    cost = settings.get_member_cost()
    
    text = (
        "🚀 **تمويل مشتركين**\n\n"
        f"💰 تكلفة العضو الواحد: **{cost}** نقطة\n"
        f"📊 الأرقام المتاحة: **{available}** عضو\n\n"
        "أرسل **عدد الأعضاء** الذي تريد تمويلهم (مثلاً: 10)\n"
        "أو أرسل /cancel للإلغاء."
    )
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # بدء محادثة التمويل
    return FUNDING_MEMBERS

async def funding_members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال عدد الأعضاء من المستخدم"""
    try:
        members_count = int(update.message.text.strip())
        
        if members_count <= 0:
            await update.message.reply_text("❌ يرجى إرسال رقم صحيح أكبر من 0.")
            return FUNDING_MEMBERS
        
        # التحقق من توفر أرقام كافية
        available = stats.get_available_numbers()
        if members_count > available:
            await update.message.reply_text(
                f"❌ العدد المطلوب أكبر من المتاح!\n"
                f"المتاح: {available}\n"
                f"الرجاء إدخال عدد أقل."
            )
            return FUNDING_MEMBERS
        
        # حساب التكلفة
        cost = helpers.calculate_cost(members_count, settings.get_member_cost())
        
        # التحقق من الرصيد
        user = user_manager.get_user(update.effective_user.id)
        if user['points'] < cost:
            await update.message.reply_text(
                f"❌ رصيدك غير كافٍ!\n"
                f"المطلوب: {cost} نقطة\n"
                f"رصيدك: {user['points']} نقطة\n\n"
                f"يمكنك تجميع المزيد من النقاط عبر رابط الدعوة."
            )
            return ConversationHandler.END
        
        # تخزين البيانات مؤقتاً
        context.user_data['funding_members'] = members_count
        context.user_data['funding_cost'] = cost
        
        await update.message.reply_text(
            f"✅ تم استلام الطلب!\n"
            f"عدد الأعضاء: {members_count}\n"
            f"التكلفة: {cost} نقطة\n\n"
            f"الآن أرسل **رابط القناة أو المجموعة** التي تريد تمويلها.\n"
            f"ملاحظة: يجب أن يكون البوت **مشرفاً** في القناة."
        )
        
        return FUNDING_LINK
        
    except ValueError:
        await update.message.reply_text("❌ يرجى إرسال رقم صحيح.")
        return FUNDING_MEMBERS

async def funding_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال رابط القناة من المستخدم"""
    link = update.message.text.strip()
    
    # بدء عملية التمويل
    success = await funding_manager.start_funding(
        update.effective_user.id,
        context.user_data['funding_members'],
        link,
        context
    )
    
    if success:
        await update.message.reply_text("✅ جاري بدء عملية التمويل...")
    else:
        await update.message.reply_text(
            "❌ فشل بدء عملية التمويل. تأكد من الرابط وصلاحيات البوت.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 العودة", callback_data="back_to_main")
            ]])
        )
    
    return ConversationHandler.END

async def show_my_funding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض تمويلات المستخدم"""
    query = update.callback_query
    user_id = query.from_user.id
    
    funding_list = funding_manager.get_user_funding(user_id)
    
    if not funding_list:
        await query.edit_message_text(
            "📊 لا توجد تمويلات سابقة.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 العودة", callback_data="back_to_main")
            ]])
        )
        return
    
    text = "📊 **تمويلاتي**\n\n"
    
    for fund in funding_list[:5]:  # آخر 5 تمويلات
        status_emoji = {
            'pending': '⏳',
            'completed': '✅',
            'cancelled': '❌'
        }.get(fund['status'], '❓')
        
        text += (
            f"{status_emoji} **{fund['chat_title']}**\n"
            f"🆔: {fund['request_id']}\n"
            f"👥 الأعضاء: {fund['members_count']}\n"
            f"✅ المضاف: {fund['added_count']}\n"
            f"💰 التكلفة: {fund['cost_points']}\n"
            f"📅 {fund['created_at'][:16]}\n"
            f"الحالة: {fund['status']}\n"
            f"{'─' * 20}\n"
        )
    
    keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="back_to_main")]]
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إحصائيات المستخدم"""
    query = update.callback_query
    user_id = query.from_user.id
    
    user = user_manager.get_user(user_id)
    if not user:
        await query.edit_message_text("❌ المستخدم غير موجود.")
        return
    
    # إحصائيات إضافية
    total_funding = db.execute_query(
        "SELECT COUNT(*) as count, SUM(members_count) as total FROM funding_requests WHERE user_id = ? AND status = 'completed'",
        (user_id,),
        fetch_one=True
    )
    
    # تاريخ الانضمام
    joined = datetime.strptime(user['joined_date'], '%Y-%m-%d %H:%M:%S')
    days_in_bot = (datetime.now() - joined).days
    
    text = (
        f"📈 **إحصائياتك في البوت**\n\n"
        f"🆔 **الايدي:** `{user_id}`\n"
        f"👤 **اليوزر:** @{user['username'] or 'لا يوجد'}\n"
        f"💰 **النقاط:** {user['points']}\n"
        f"👥 **الدعوات:** {user['referrals']}\n"
        f"🚀 **التمويلات المنفذة:** {total_funding['count'] if total_funding else 0}\n"
        f"👤 **الأعضاء المضافين:** {total_funding['total'] if total_funding else 0}\n"
        f"📅 **عضو منذ:** {days_in_bot} يوم\n"
        f"🕐 **آخر نشاط:** {user['last_active'][:16]}\n"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="back_to_main")]]
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """العودة إلى القائمة الرئيسية"""
    query = update.callback_query
    user_id = query.from_user.id
    
    user = user_manager.get_user(user_id)
    welcome_text = settings.get_welcome_message(user_id, query.from_user.username or "لا يوجد", user['points'])
    
    keyboard = [
        [InlineKeyboardButton("💰 تجميع النقاط", callback_data="earn_points")],
        [InlineKeyboardButton("🚀 تمويل مشتركين", callback_data="start_funding")],
        [InlineKeyboardButton("📊 تمويلاتي", callback_data="my_funding")],
        [InlineKeyboardButton("📈 احصائياتي", callback_data="my_stats")],
        [InlineKeyboardButton("🆘 الدعم الفني", url=f"https://t.me/{settings.get_support_username()}")],
        [InlineKeyboardButton("📢 قناة البوت", url=f"https://t.me/{settings.get_channel_username()}")]
    ]
    
    await query.edit_message_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التحقق من الاشتراك عند الضغط على الزر"""
    query = update.callback_query
    user_id = query.from_user.id
    
    is_subscribed, not_joined = await force_manager.check_all_memberships(user_id, context)
    
    if is_subscribed or user_id in ADMIN_IDS:
        # إعادة عرض القائمة الرئيسية
        user = user_manager.get_user(user_id)
        welcome_text = settings.get_welcome_message(user_id, query.from_user.username or "لا يوجد", user['points'])
        
        keyboard = [
            [InlineKeyboardButton("💰 تجميع النقاط", callback_data="earn_points")],
            [InlineKeyboardButton("🚀 تمويل مشتركين", callback_data="start_funding")],
            [InlineKeyboardButton("📊 تمويلاتي", callback_data="my_funding")],
            [InlineKeyboardButton("📈 احصائياتي", callback_data="my_stats")],
            [InlineKeyboardButton("🆘 الدعم الفني", url=f"https://t.me/{settings.get_support_username()}")],
            [InlineKeyboardButton("📢 قناة البوت", url=f"https://t.me/{settings.get_channel_username()}")]
        ]
        
        await query.edit_message_text(
            welcome_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        text = "🚫 لم تشترك في جميع القنوات بعد.\n\n"
        keyboard = force_manager.get_channels_keyboard()
        await query.edit_message_text(text, reply_markup=keyboard)

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إلغاء المحادثة"""
    await update.message.reply_text(
        "✅ تم الإلغاء.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 العودة للقائمة", callback_data="back_to_main")
        ]])
    )
    return ConversationHandler.END

# ==================== لوحة تحكم المشرف ====================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض لوحة تحكم المشرف"""
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    text = (
        "🔧 **لوحة تحكم المشرف**\n\n"
        "اختر أحد الخيارات التالية:"
    )
    
    keyboard = [
        [InlineKeyboardButton("📊 إحصائيات البوت", callback_data="admin_stats")],
        [InlineKeyboardButton("💰 شحن/خصم رصيد", callback_data="admin_points")],
        [InlineKeyboardButton("📁 إدارة ملفات الأرقام", callback_data="admin_files")],
        [InlineKeyboardButton("🆘 إعدادات الدعم", callback_data="admin_support")],
        [InlineKeyboardButton("📢 إعدادات القناة", callback_data="admin_channel")],
        [InlineKeyboardButton("🚫 إدارة الحظر", callback_data="admin_ban")],
        [InlineKeyboardButton("🎁 تعديل مكافأة الدعوة", callback_data="admin_reward")],
        [InlineKeyboardButton("💰 تعديل سعر العضو", callback_data="admin_cost")],
        [InlineKeyboardButton("📢 إدارة القنوات الإجبارية", callback_data="admin_force")],
        [InlineKeyboardButton("📝 تعديل رسالة الترحيب", callback_data="admin_welcome")],
        [InlineKeyboardButton("💾 نسخة احتياطية", callback_data="admin_backup")],
    ]
    
    if update.message:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.callback_query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def admin_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إحصائيات البوت للمشرف"""
    query = update.callback_query
    
    # إحصائيات شاملة
    total_users = stats.get_total_users()
    active_users = stats.get_active_users()
    banned_users = stats.get_banned_users()
    total_points = stats.get_total_points()
    total_funding = stats.get_total_funding()
    total_members = stats.get_total_members_added()
    available_numbers = stats.get_available_numbers()
    total_numbers = stats.get_total_numbers()
    
    # إحصائيات الملفات
    file_stats = file_manager.get_file_stats()
    
    # أفضل المستخدمين
    top_users = stats.get_top_users(5)
    top_text = ""
    for i, user in enumerate(top_users, 1):
        top_text += f"{i}. @{user['username'] or 'مجهول'} - {user['points']} نقطة\n"
    
    text = (
        f"📊 **إحصائيات البوت**\n\n"
        f"👥 **المستخدمين**\n"
        f"المجموع: {total_users}\n"
        f"النشطين (7 أيام): {active_users}\n"
        f"المحظورين: {banned_users}\n\n"
        f"💰 **النقاط**\n"
        f"إجمالي النقاط: {total_points}\n"
        f"معدل النقاط: {total_points // max(total_users, 1)}\n\n"
        f"🚀 **التمويل**\n"
        f"عمليات التمويل: {total_funding}\n"
        f"الأعضاء المضافين: {total_members}\n\n"
        f"📁 **الأرقام**\n"
        f"الإجمالي: {total_numbers}\n"
        f"المستخدم: {file_stats['used_numbers']}\n"
        f"المتبقي: {file_stats['available']}\n"
        f"الملفات: {file_stats['total_files']}\n\n"
        f"🏆 **أفضل 5 مستخدمين**\n"
        f"{top_text}"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_points_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية شحن/خصم الرصيد"""
    query = update.callback_query
    
    text = (
        "💰 **شحن/خصم رصيد**\n\n"
        "أرسل **ايدي المستخدم** الذي تريد تعديل رصيده:\n"
        "أو أرسل /cancel للإلغاء."
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    return ADMIN_USER_ID

async def admin_user_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال ايدي المستخدم"""
    try:
        user_id = int(update.message.text.strip())
        user = user_manager.get_user(user_id)
        
        if not user:
            await update.message.reply_text("❌ المستخدم غير موجود في قاعدة البيانات.")
            return ConversationHandler.END
        
        context.user_data['target_user_id'] = user_id
        context.user_data['target_user'] = user
        
        await update.message.reply_text(
            f"👤 المستخدم: @{user['username'] or 'مجهول'}\n"
            f"💰 الرصيد الحالي: {user['points']}\n\n"
            f"أرسل المبلغ الذي تريد **شحنه** (استخدم - للخصم)\n"
            f"مثال: 100 أو -50"
        )
        return ADMIN_AMOUNT
        
    except ValueError:
        await update.message.reply_text("❌ يرجى إرسال رقم صحيح.")
        return ADMIN_USER_ID

async def admin_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال المبلغ وتعديل الرصيد"""
    try:
        amount = int(update.message.text.strip())
        user_id = context.user_data['target_user_id']
        
        success = user_manager.update_points(
            user_id,
            amount,
            "admin_adjust",
            f"تعديل بواسطة المشرف"
        )
        
        if success:
            new_balance = user_manager.get_user(user_id)['points']
            await update.message.reply_text(
                f"✅ تم تعديل الرصيد بنجاح!\n"
                f"المبلغ: {amount:+d}\n"
                f"الرصيد الجديد: {new_balance}"
            )
            
            # إشعار المستخدم
            action = "شحن" if amount > 0 else "خصم"
            try:
                await context.bot.send_message(
                    user_id,
                    f"💰 تم {action} رصيدك بمقدار {abs(amount)} نقطة بواسطة المشرف.\n"
                    f"رصيدك الحالي: {new_balance}"
                )
            except:
                pass
        else:
            await update.message.reply_text("❌ فشل تعديل الرصيد.")
        
        # عرض لوحة التحكم مجدداً
        await admin_panel(update, context)
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ يرجى إرسال رقم صحيح.")
        return ADMIN_AMOUNT

async def admin_files_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة ملفات الأرقام"""
    query = update.callback_query
    
    file_stats = file_manager.get_file_stats()
    files = file_manager.get_all_files()
    
    text = (
        f"📁 **إدارة ملفات الأرقام**\n\n"
        f"إجمالي الملفات: {file_stats['total_files']}\n"
        f"إجمالي الأرقام: {file_stats['total_numbers']}\n"
        f"الأرقام المستخدمة: {file_stats['used_numbers']}\n"
        f"الأرقام المتاحة: {file_stats['available']}\n\n"
    )
    
    if files:
        text += "**الملفات المضافة:**\n"
        for file in files[:5]:
            text += f"📄 {file['file_name']} - {file['numbers_count']} رقم - {file['added_date'][:16]}\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ إضافة ملف جديد", callback_data="admin_add_file")],
        [InlineKeyboardButton("🗑 حذف ملف", callback_data="admin_delete_file")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_add_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية إضافة ملف"""
    query = update.callback_query
    
    await query.edit_message_text(
        "📁 أرسل ملف **txt** يحتوي على أرقام الهواتف (رقم واحد في كل سطر).\n"
        "أو أرسل /cancel للإلغاء."
    )
    return ADMIN_FILE

async def admin_file_receive_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال ملف الأرقام"""
    if not update.message.document:
        await update.message.reply_text("❌ يرجى إرسال ملف بصيغة txt.")
        return ADMIN_FILE
    
    file = update.message.document
    if not file.file_name.endswith('.txt'):
        await update.message.reply_text("❌ الملف يجب أن يكون بصيغة txt فقط.")
        return ADMIN_FILE
    
    try:
        # تحميل الملف
        new_file = await context.bot.get_file(file.file_id)
        file_content = await new_file.download_as_bytearray()
        content = file_content.decode('utf-8')
        
        # معالجة الملف
        success, count, numbers = await file_manager.process_numbers_file(
            content,
            f"{int(time.time())}_{file.file_name}",
            update.effective_user.id
        )
        
        if success:
            await update.message.reply_text(
                f"✅ تم إضافة الملف بنجاح!\n"
                f"إجمالي الأرقام: {count}\n"
                f"الأرقام المكررة: {len(numbers) - count}"
            )
        else:
            await update.message.reply_text("❌ فشل معالجة الملف.")
        
    except Exception as e:
        logger.error(f"Error processing file: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء معالجة الملف.")
    
    # العودة للوحة التحكم
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_delete_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف ملف"""
    query = update.callback_query
    
    files = file_manager.get_all_files()
    if not files:
        await query.edit_message_text(
            "❌ لا توجد ملفات للحذف.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")
            ]])
        )
        return
    
    keyboard = []
    for file in files[:10]:
        keyboard.append([
            InlineKeyboardButton(
                f"📄 {file['file_name']} ({file['numbers_count']} رقم)",
                callback_data=f"delete_file_{file['id']}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
    
    await query.edit_message_text(
        "اختر الملف الذي تريد حذفه:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def delete_file_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف ملف محدد"""
    query = update.callback_query
    file_id = int(query.data.split("_")[2])
    
    success = file_manager.delete_file(file_id)
    
    if success:
        await query.answer("✅ تم حذف الملف بنجاح!")
        await query.edit_message_text("✅ تم حذف الملف.")
    else:
        await query.answer("❌ فشل حذف الملف!")
    
    # العودة لإدارة الملفات
    await admin_files_handler(update, context)

async def admin_support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعديل حساب الدعم"""
    query = update.callback_query
    
    current = settings.get_support_username()
    
    await query.edit_message_text(
        f"🆘 **إعدادات الدعم الفني**\n\n"
        f"الحالي: @{current}\n\n"
        f"أرسل اسم المستخدم الجديد للدعم (بدون @):\n"
        f"أو أرسل /cancel للإلغاء."
    )
    return ADMIN_SUPPORT

async def admin_support_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحديث حساب الدعم"""
    username = update.message.text.strip().replace('@', '')
    
    settings.set('support_username', username)
    
    await update.message.reply_text(f"✅ تم تحديث حساب الدعم إلى: @{username}")
    
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعديل رابط القناة"""
    query = update.callback_query
    
    current = settings.get_channel_username()
    
    await query.edit_message_text(
        f"📢 **إعدادات قناة البوت**\n\n"
        f"الحالي: @{current}\n\n"
        f"أرسل اسم المستخدم الجديد للقناة (بدون @):\n"
        f"أو أرسل /cancel للإلغاء."
    )
    return ADMIN_CHANNEL

async def admin_channel_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحديث رابط القناة"""
    username = update.message.text.strip().replace('@', '')
    
    settings.set('channel_username', username)
    
    await update.message.reply_text(f"✅ تم تحديث رابط القناة إلى: @{username}")
    
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_ban_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة الحظر"""
    query = update.callback_query
    
    keyboard = [
        [InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_ban_user")],
        [InlineKeyboardButton("✅ رفع حظر", callback_data="admin_unban_user")],
        [InlineKeyboardButton("📋 قائمة المحظورين", callback_data="admin_banned_list")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
    ]
    
    await query.edit_message_text(
        "🚫 **إدارة الحظر**\n\nاختر الإجراء المطلوب:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_ban_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية حظر مستخدم"""
    query = update.callback_query
    
    await query.edit_message_text(
        "🚫 أرسل **ايدي المستخدم** الذي تريد حظره:\n"
        "أو أرسل /cancel للإلغاء."
    )
    return ADMIN_BAN_REASON

async def admin_ban_user_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنفيذ حظر مستخدم"""
    try:
        user_id = int(update.message.text.strip())
        
        if user_id in ADMIN_IDS:
            await update.message.reply_text("❌ لا يمكن حظر مشرف.")
            return ConversationHandler.END
        
        if user_manager.is_banned(user_id):
            await update.message.reply_text("❌ المستخدم محظور بالفعل.")
            return ConversationHandler.END
        
        context.user_data['ban_user_id'] = user_id
        
        await update.message.reply_text(
            "أرسل سبب الحظر (اختياري) أو أرسل /skip لتخطي:"
        )
        return ADMIN_BAN_REASON + 1  # رقم مؤقت للحالة
        
    except ValueError:
        await update.message.reply_text("❌ يرجى إرسال رقم صحيح.")
        return ADMIN_BAN_REASON

async def admin_ban_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال سبب الحظر"""
    reason = update.message.text.strip() if update.message.text != "/skip" else "بدون سبب"
    
    user_id = context.user_data['ban_user_id']
    success = user_manager.ban_user(user_id, update.effective_user.id, reason)
    
    if success:
        await update.message.reply_text(f"✅ تم حظر المستخدم {user_id}\nالسبب: {reason}")
    else:
        await update.message.reply_text("❌ فشل حظر المستخدم.")
    
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_unban_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رفع الحظر عن مستخدم"""
    query = update.callback_query
    
    await query.edit_message_text(
        "✅ أرسل **ايدي المستخدم** الذي تريد رفع الحظر عنه:\n"
        "أو أرسل /cancel للإلغاء."
    )
    return ADMIN_USER_ID  # إعادة استخدام حالة استقبال الايدي

async def admin_unban_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنفيذ رفع الحظر"""
    try:
        user_id = int(update.message.text.strip())
        
        if not user_manager.is_banned(user_id):
            await update.message.reply_text("❌ المستخدم غير محظور.")
            return ConversationHandler.END
        
        success = user_manager.unban_user(user_id)
        
        if success:
            await update.message.reply_text(f"✅ تم رفع الحظر عن المستخدم {user_id}")
        else:
            await update.message.reply_text("❌ فشل رفع الحظر.")
        
    except ValueError:
        await update.message.reply_text("❌ يرجى إرسال رقم صحيح.")
        return ADMIN_USER_ID
    
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_banned_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة المحظورين"""
    query = update.callback_query
    
    banned = db.execute_query("""
        SELECT u.user_id, u.username, b.reason, b.banned_date 
        FROM banned_users b
        JOIN users u ON u.user_id = b.user_id
        ORDER BY b.banned_date DESC
        LIMIT 20
    """)
    
    if not banned:
        await query.edit_message_text(
            "📋 لا يوجد مستخدمين محظورين.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")
            ]])
        )
        return
    
    text = "📋 **قائمة المحظورين**\n\n"
    for user in banned:
        text += (
            f"🆔 `{user['user_id']}`\n"
            f"👤 @{user['username'] or 'مجهول'}\n"
            f"📅 {user['banned_date'][:16]}\n"
            f"📝 {user['reason'] or 'بدون سبب'}\n"
            f"{'─' * 20}\n"
        )
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_reward_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعديل مكافأة الدعوة"""
    query = update.callback_query
    
    current = settings.get_referral_reward()
    
    await query.edit_message_text(
        f"🎁 **مكافأة الدعوة**\n\n"
        f"الحالية: {current} نقطة\n\n"
        f"أرسل القيمة الجديدة:\n"
        f"أو أرسل /cancel للإلغاء."
    )
    return ADMIN_REWARD

async def admin_reward_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحديث مكافأة الدعوة"""
    try:
        value = int(update.message.text.strip())
        if value <= 0:
            raise ValueError
        
        settings.set('referral_reward', str(value))
        
        await update.message.reply_text(f"✅ تم تحديث مكافأة الدعوة إلى: {value} نقطة")
        
    except ValueError:
        await update.message.reply_text("❌ يرجى إرسال رقم صحيح أكبر من 0.")
        return ADMIN_REWARD
    
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_cost_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعديل سعر العضو"""
    query = update.callback_query
    
    current = settings.get_member_cost()
    
    await query.edit_message_text(
        f"💰 **سعر العضو**\n\n"
        f"الحالي: {current} نقطة\n\n"
        f"أرسل القيمة الجديدة:\n"
        f"أو أرسل /cancel للإلغاء."
    )
    return ADMIN_COST

async def admin_cost_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحديث سعر العضو"""
    try:
        value = int(update.message.text.strip())
        if value <= 0:
            raise ValueError
        
        settings.set('member_cost', str(value))
        
        await update.message.reply_text(f"✅ تم تحديث سعر العضو إلى: {value} نقطة")
        
    except ValueError:
        await update.message.reply_text("❌ يرجى إرسال رقم صحيح أكبر من 0.")
        return ADMIN_COST
    
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_force_channels_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة القنوات الإجبارية"""
    query = update.callback_query
    
    channels = force_manager.get_all_channels()
    
    text = "📢 **القنوات الإجبارية**\n\n"
    if channels:
        for i, channel in enumerate(channels, 1):
            text += f"{i}. {channel['channel_title']} - @{channel['channel_username']}\n"
    else:
        text += "لا توجد قنوات إجبارية.\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ إضافة قناة", callback_data="admin_add_force")],
        [InlineKeyboardButton("🗑 حذف قناة", callback_data="admin_remove_force")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_add_force_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة قناة إجبارية جديدة"""
    query = update.callback_query
    
    await query.edit_message_text(
        "📢 أرسل **معرف القناة** أو **الرابط** (مثال: @channel أو https://t.me/channel):\n"
        "أو أرسل /cancel للإلغاء."
    )
    return ADMIN_FORCE_CHANNEL

async def admin_add_force_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنفيذ إضافة القناة الإجبارية"""
    try:
        channel_input = update.message.text.strip()
        chat_info = await funding_manager.extract_chat_info(channel_input, context)
        
        if not chat_info:
            await update.message.reply_text(
                "❌ لم أتمكن من العثور على القناة. تأكد من صحة الرابط وأن البوت مشرف فيها."
            )
            return ADMIN_FORCE_CHANNEL
        
        # إضافة القناة
        success = force_manager.add_channel(
            chat_info['chat_id'],
            chat_info['username'] or chat_info['chat_id'],
            chat_info['title'],
            update.effective_user.id
        )
        
        if success:
            await update.message.reply_text(f"✅ تم إضافة القناة {chat_info['title']} بنجاح!")
        else:
            await update.message.reply_text("❌ فشل إضافة القناة.")
        
    except Exception as e:
        logger.error(f"Error adding force channel: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء إضافة القناة.")
    
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_remove_force_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف قناة إجبارية"""
    query = update.callback_query
    
    channels = force_manager.get_all_channels()
    if not channels:
        await query.edit_message_text(
            "❌ لا توجد قنوات للحذف.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")
            ]])
        )
        return
    
    keyboard = []
    for channel in channels:
        keyboard.append([
            InlineKeyboardButton(
                f"🗑 {channel['channel_title']}",
                callback_data=f"remove_force_{channel['channel_id']}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
    
    await query.edit_message_text(
        "اختر القناة التي تريد حذفها:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def remove_force_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف قناة إجبارية محددة"""
    query = update.callback_query
    channel_id = query.data.split("_")[2]
    
    success = force_manager.remove_channel(channel_id)
    
    if success:
        await query.answer("✅ تم حذف القناة بنجاح!")
    else:
        await query.answer("❌ فشل حذف القناة!")
    
    # العودة لإدارة القنوات
    await admin_force_channels_handler(update, context)

async def admin_welcome_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعديل رسالة الترحيب"""
    query = update.callback_query
    
    current = settings.get('welcome_message', 
        "👋 مرحباً بك في بوت التمويل!\nنقاطك: {points}\nايديك: {user_id}\n@{username}")
    
    await query.edit_message_text(
        f"📝 **رسالة الترحيب الحالية:**\n\n{current}\n\n"
        f"أرسل الرسالة الجديدة (يمكنك استخدام المتغيرات: {{points}}, {{user_id}}, {{username}}):\n"
        f"أو أرسل /cancel للإلغاء."
    )
    return ADMIN_REWARD  # إعادة استخدام حالة مؤقتة

async def admin_welcome_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحديث رسالة الترحيب"""
    new_message = update.message.text.strip()
    
    settings.set('welcome_message', new_message)
    
    await update.message.reply_text("✅ تم تحديث رسالة الترحيب بنجاح!")
    
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_backup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إنشاء نسخة احتياطية"""
    query = update.callback_query
    
    try:
        backup_path = helpers.create_backup()
        
        # إرسال الملف
        await context.bot.send_document(
            query.message.chat_id,
            document=open(backup_path, 'rb'),
            filename=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
            caption="✅ نسخة احتياطية من قاعدة البيانات"
        )
        
        await query.answer("✅ تم إنشاء النسخة الاحتياطية!")
        
    except Exception as e:
        logger.error(f"Error creating backup: {e}")
        await query.edit_message_text("❌ فشل إنشاء النسخة الاحتياطية.")
    
    # العودة للوحة التحكم
    await admin_panel(update, context)

async def approve_funding(update: Update, context: ContextTypes.DEFAULT_TYPE, request_id: int):
    """الموافقة على طلب تمويل"""
    query = update.callback_query
    
    # تحديث الحالة
    db.execute_query(
        "UPDATE funding_requests SET status = 'approved' WHERE request_id = ?",
        (request_id,)
    )
    
    await query.edit_message_text("✅ تمت الموافقة على طلب التمويل.")

async def reject_funding(update: Update, context: ContextTypes.DEFAULT_TYPE, request_id: int):
    """رفض طلب تمويل"""
    query = update.callback_query
    
    # استرجاع معلومات الطلب
    request = db.execute_query(
        "SELECT * FROM funding_requests WHERE request_id = ?",
        (request_id,),
        fetch_one=True
    )
    
    if request:
        # إعادة النقاط للمستخدم
        user_manager.update_points(
            request['user_id'],
            request['cost_points'],
            "refund",
            "استرداد نقاط تمويل ملغي"
        )
        
        # تحديث الحالة
        db.execute_query(
            "UPDATE funding_requests SET status = 'rejected' WHERE request_id = ?",
            (request_id,)
        )
        
        # إشعار المستخدم
        try:
            await context.bot.send_message(
                request['user_id'],
                f"❌ تم رفض طلب التمويل الخاص بك.\n"
                f"تم استرداد {request['cost_points']} نقطة إلى رصيدك."
            )
        except:
            pass
    
    await query.edit_message_text("❌ تم رفض طلب التمويل.")

async def ban_user_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id: int):
    """حظر مستخدم من خلال إشعار التمويل"""
    query = update.callback_query
    
    if target_id in ADMIN_IDS:
        await query.answer("⛔ لا يمكن حظر مشرف!")
        return
    
    success = user_manager.ban_user(target_id, query.from_user.id, "حظر من إشعار تمويل")
    
    if success:
        await query.edit_message_text(f"✅ تم حظر المستخدم {target_id}.")
    else:
        await query.answer("❌ فشل حظر المستخدم.")

async def admin_back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """العودة إلى لوحة التحكم الرئيسية"""
    await admin_panel(update, context)

# ==================== معالج الأخطاء ====================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأخطاء العام"""
    try:
        raise context.error
    except Exception as e:
        logger.error(f"Update {update} caused error {e}")
        
        # إشعار المشرفين بخطأ كبير
        if update and update.effective_user:
            error_text = f"⚠️ خطأ في البوت:\n{str(e)[:200]}"
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(admin_id, error_text)
                except:
                    pass

# ==================== تهيئة البوت وتشغيله ====================

def main():
    """الدالة الرئيسية لتشغيل البوت"""
    
    # إنشاء التطبيق
    application = Application.builder().token(BOT_TOKEN).build()
    
    # ========== معالجي الأوامر العامة ==========
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^(?!admin_|delete_file_|remove_force_).*$"))
    
    # ========== معالجي لوحة التحكم ==========
    application.add_handler(CallbackQueryHandler(admin_stats_handler, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(admin_points_handler, pattern="^admin_points$"))
    application.add_handler(CallbackQueryHandler(admin_files_handler, pattern="^admin_files$"))
    application.add_handler(CallbackQueryHandler(admin_add_file_handler, pattern="^admin_add_file$"))
    application.add_handler(CallbackQueryHandler(admin_delete_file_handler, pattern="^admin_delete_file$"))
    application.add_handler(CallbackQueryHandler(delete_file_callback, pattern="^delete_file_"))
    application.add_handler(CallbackQueryHandler(admin_support_handler, pattern="^admin_support$"))
    application.add_handler(CallbackQueryHandler(admin_channel_handler, pattern="^admin_channel$"))
    application.add_handler(CallbackQueryHandler(admin_ban_handler, pattern="^admin_ban$"))
    application.add_handler(CallbackQueryHandler(admin_ban_user_handler, pattern="^admin_ban_user$"))
    application.add_handler(CallbackQueryHandler(admin_unban_user_handler, pattern="^admin_unban_user$"))
    application.add_handler(CallbackQueryHandler(admin_banned_list_handler, pattern="^admin_banned_list$"))
    application.add_handler(CallbackQueryHandler(admin_reward_handler, pattern="^admin_reward$"))
    application.add_handler(CallbackQueryHandler(admin_cost_handler, pattern="^admin_cost$"))
    application.add_handler(CallbackQueryHandler(admin_force_channels_handler, pattern="^admin_force$"))
    application.add_handler(CallbackQueryHandler(admin_add_force_handler, pattern="^admin_add_force$"))
    application.add_handler(CallbackQueryHandler(admin_remove_force_handler, pattern="^admin_remove_force$"))
    application.add_handler(CallbackQueryHandler(remove_force_callback, pattern="^remove_force_"))
    application.add_handler(CallbackQueryHandler(admin_welcome_handler, pattern="^admin_welcome$"))
    application.add_handler(CallbackQueryHandler(admin_backup_handler, pattern="^admin_backup$"))
    application.add_handler(CallbackQueryHandler(admin_back_handler, pattern="^admin_back$"))
    
    # ========== معالجي محادثة التمويل ==========
    funding_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_funding_cmd, pattern="^start_funding$")],
        states={
            FUNDING_MEMBERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, funding_members_handler)],
            FUNDING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, funding_link_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(funding_conv)
    
    # ========== معالجي محادثة شحن/خصم الرصيد ==========
    points_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_points_handler, pattern="^admin_points$")],
        states={
            ADMIN_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_user_id_handler)],
            ADMIN_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_amount_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(points_conv)
    
    # ========== معالجي محادثة إضافة ملف ==========
    file_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_file_handler, pattern="^admin_add_file$")],
        states={
            ADMIN_FILE: [MessageHandler(filters.Document.ALL, admin_file_receive_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(file_conv)
    
    # ========== معالجي محادثة تحديث الدعم ==========
    support_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_support_handler, pattern="^admin_support$")],
        states={
            ADMIN_SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_support_update_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(support_conv)
    
    # ========== معالجي محادثة تحديث القناة ==========
    channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_channel_handler, pattern="^admin_channel$")],
        states={
            ADMIN_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_channel_update_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(channel_conv)
    
    # ========== معالجي محادثة مكافأة الدعوة ==========
    reward_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_reward_handler, pattern="^admin_reward$")],
        states={
            ADMIN_REWARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reward_update_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(reward_conv)
    
    # ========== معالجي محادثة سعر العضو ==========
    cost_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_cost_handler, pattern="^admin_cost$")],
        states={
            ADMIN_COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_cost_update_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(cost_conv)
    
    # ========== معالجي محادثة إضافة قناة إجبارية ==========
    force_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_force_handler, pattern="^admin_add_force$")],
        states={
            ADMIN_FORCE_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_force_execute)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(force_conv)
    
    # ========== معالجي محادثة حظر مستخدم ==========
    ban_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_ban_user_handler, pattern="^admin_ban_user$")],
        states={
            ADMIN_BAN_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ban_reason_handler)],
            ADMIN_BAN_REASON + 1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ban_reason_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(ban_conv)
    
    # ========== معالجي محادثة رفع الحظر ==========
    unban_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_unban_user_handler, pattern="^admin_unban_user$")],
        states={
            ADMIN_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_unban_execute)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(unban_conv)
    
    # ========== معالجي محادثة رسالة الترحيب ==========
    welcome_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_welcome_handler, pattern="^admin_welcome$")],
        states={
            ADMIN_REWARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_welcome_update_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(welcome_conv)
    
    # ========== معالج الأخطاء ==========
    application.add_error_handler(error_handler)
    
    # تشغيل البوت
    print(f"{Fore.GREEN}{'='*50}")
    print(f"{Fore.GREEN}تم تشغيل بوت التمويل بنجاح!")
    print(f"{Fore.GREEN}توكن البوت: {BOT_TOKEN}")
    print(f"{Fore.GREEN}المشرفون: {ADMIN_IDS}")
    print(f"{Fore.GREEN}{'='*50}")
    
    # بدء البوت
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"{Fore.YELLOW}\nتم إيقاف البوت بواسطة المستخدم.")
    except Exception as e:
        print(f"{Fore.RED}\nخطأ غير متوقع: {e}")
        logger.error(f"Fatal error: {e}", exc_info=True)
