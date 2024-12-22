import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
import yt_dlp
from datetime import datetime
import concurrent.futures
import queue
import asyncio
from dotenv import load_dotenv
import json
from pathlib import Path
import time

# تحميل المتغيرات البيئية
load_dotenv()

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# إعداد المتغيرات العامة
TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')

# إنشاء مجمع المهام
download_executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)

# بيانات المستخدمين
users_data = {
    'users': {},  # معلومات المستخدمين
    'last_active': {},  # آخر نشاط
    'total_downloads': 0,  # إجمالي التحميلات
}

def save_users_data():
    """حفظ بيانات المستخدمين في ملف"""
    data_file = Path('users_data.json')
    # تحويل التواريخ إلى نص قبل الحفظ
    data_to_save = {
        'users': {
            str(uid): {
                **user_data,
                'join_date': user_data['join_date'].isoformat() if isinstance(user_data.get('join_date'), datetime) else None,
                'last_active': user_data['last_active'].isoformat() if isinstance(user_data.get('last_active'), datetime) else None
            }
            for uid, user_data in users_data['users'].items()
        },
        'last_active': {
            str(uid): time.isoformat() if isinstance(time, datetime) else None
            for uid, time in users_data['last_active'].items()
        },
        'total_downloads': users_data['total_downloads']
    }
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data_to_save, f, ensure_ascii=False, indent=2)

def load_users_data():
    """تحميل بيانات المستخدمين من الملف"""
    data_file = Path('users_data.json')
    if data_file.exists():
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # تحويل النصوص إلى تواريخ
            users_data['users'] = {
                int(uid): {
                    **user_data,
                    'join_date': datetime.fromisoformat(user_data['join_date']) if user_data.get('join_date') else None,
                    'last_active': datetime.fromisoformat(user_data['last_active']) if user_data.get('last_active') else None
                }
                for uid, user_data in data['users'].items()
            }
            users_data['last_active'] = {
                int(uid): datetime.fromisoformat(time) if time else None
                for uid, time in data['last_active'].items()
            }
            users_data['total_downloads'] = data['total_downloads']

def update_user_stats(user_id, action='login'):
    """تحديث إحصائيات المستخدم"""
    try:
        if isinstance(user_id, Update):
            if not user_id.message:
                return
            user = user_id.message.from_user
            user_id = user.id
            
            # تحديث أو إنشاء بيانات المستخدم
            if user_id not in users_data['users']:
                users_data['users'][user_id] = {
                    'user_id': user_id,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'username': user.username,
                    'language_code': user.language_code,
                    'downloads': 0,
                    'youtube_downloads': 0,
                    'snapchat_downloads': 0,
                    'join_date': datetime.now(),
                    'last_active': datetime.now(),
                    'is_premium': False,
                    'status': 'active',
                    'total_interactions': 0,
                    'last_interaction_type': None,
                }
                logger.info(f"مستخدم جديد: {user.first_name} (ID: {user_id})")
            
            # تحديث البيانات الموجودة
            user_data = users_data['users'][user_id]
            user_data['last_active'] = datetime.now()
            
            # التأكد من وجود جميع المفاتيح المطلوبة
            if 'total_interactions' not in user_data:
                user_data['total_interactions'] = 0
            if 'status' not in user_data:
                user_data['status'] = 'active'
            if 'last_interaction_type' not in user_data:
                user_data['last_interaction_type'] = None
            
            user_data['total_interactions'] += 1
            
        if action == 'login':
            users_data['last_active'][user_id] = datetime.now()
            if user_id in users_data['users']:
                users_data['users'][user_id]['status'] = 'active'
        elif action == 'download':
            users_data['total_downloads'] += 1
            if user_id in users_data['users']:
                users_data['users'][user_id]['downloads'] += 1
                users_data['users'][user_id]['last_interaction_type'] = 'download'
            users_data['last_active'][user_id] = datetime.now()
        elif action == 'youtube':
            if user_id in users_data['users']:
                users_data['users'][user_id]['youtube_downloads'] += 1
        elif action == 'snapchat':
            if user_id in users_data['users']:
                users_data['users'][user_id]['snapchat_downloads'] += 1
        
        # حفظ البيانات بعد كل تحديث
        save_users_data()
        
    except Exception as e:
        logger.error(f"خطأ في تحديث بيانات المستخدم: {str(e)}")
        # إنشاء بيانات جديدة في حالة وجود خطأ
        if isinstance(user_id, Update):
            user = user_id.message.from_user
            user_id = user.id
            users_data['users'][user_id] = {
                'user_id': user_id,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'username': user.username,
                'language_code': user.language_code,
                'downloads': 0,
                'youtube_downloads': 0,
                'snapchat_downloads': 0,
                'join_date': datetime.now(),
                'last_active': datetime.now(),
                'is_premium': False,
                'status': 'active',
                'total_interactions': 1,
                'last_interaction_type': None,
            }
            save_users_data()

def format_time_ago(time):
    """تنسيق الوقت المنقضي"""
    now = datetime.now()
    diff = now - time
    
    if diff.total_seconds() < 60:
        return "منذ لحظات"
    elif diff.total_seconds() < 3600:
        minutes = int(diff.total_seconds() / 60)
        return f"منذ {minutes} دقيقة"
    elif diff.total_seconds() < 86400:
        hours = int(diff.total_seconds() / 3600)
        return f"منذ {hours} ساعة"
    else:
        days = int(diff.total_seconds() / 86400)
        return f"منذ {days} يوم"

def show_dashboard(update: Update, context: CallbackContext):
    """عرض لوحة التحكم للمشرف"""
    if not update.message:
        return
    
    message_text = update.message.text.strip()
    user_id = str(update.message.from_user.id)
    
    if message_text.lower() == '4u':
        if user_id == ADMIN_ID:
            keyboard = [
                [InlineKeyboardButton("👥 قائمة المستخدمين", callback_data='list_users')],
                [InlineKeyboardButton("📊 إحصائيات عامة", callback_data='general_stats')],
                [InlineKeyboardButton("🔍 بحث عن مستخدم", callback_data='search_user')],
                [InlineKeyboardButton("📢 رسالة جماعية", callback_data='broadcast')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text("🎛 لوحة تحكم المشرف\nاختر ما تريد عرضه:", reply_markup=reply_markup)
        else:
            update.message.reply_text("⛔️ عذراً، هذا الأمر متاح للمشرفين فقط")

def handle_message(update: Update, context: CallbackContext):
    """معالجة الرسائل"""
    if not update.message or not update.message.text:
        return

    user = update.message.from_user
    text = update.message.text.strip()
    
    # تحديث إحصائيات المستخدم
    update_user_stats(update)
    
    # التحقق من رسالة 4u
    if text.lower() == '4u':
        show_dashboard(update, context)
        return

    # معالجة الروابط
    if is_youtube_url(text) or is_snapchat_url(text):
        handle_url(update, context)
        return

    # معالجة أزرار لوحة التحكم
    if text == "👥 معلومات المستخدمين":
        if str(user.id) != ADMIN_ID:
            update.message.reply_text("⚠️ عذراً، هذه الميزة متاحة فقط للمشرف.")
            return
            
        total_users = len(users_data['users'])
        active_today = sum(1 for last_active in users_data['last_active'].values()
                          if (datetime.now() - last_active).total_seconds() < 86400)
        total_downloads = users_data['total_downloads']
        
        user_list = []
        for uid, user_info in users_data['users'].items():
            last_active = users_data['last_active'].get(int(uid), datetime.min)
            time_diff = datetime.now() - last_active
            
            if time_diff.total_seconds() < 3600:
                status = "🟢"
            elif time_diff.total_seconds() < 86400:
                status = "🟡"
            else:
                status = "⚪️"
            
            username = user_info.get('username') or user_info.get('first_name') or uid
            downloads = user_info.get('downloads', 0)
            last_seen = format_time_ago(last_active)
            
            user_list.append(
                f"{status} *المستخدم*: {username}\n"
                f"• التحميلات: {downloads}\n"
                f"• آخر ظهور: {last_seen}\n"
            )
        
        stats_message = (
            f"📊 *إحصائيات البوت*\n\n"
            f"👥 إجمالي المستخدمين: {total_users}\n"
            f"✅ النشطين اليوم: {active_today}\n"
            f"📥 مجموع التحميلات: {total_downloads}\n\n"
            f"*قائمة المستخدمين:*\n\n"
            f"{chr(10).join(user_list[:10])}"  # عرض أول 10 مستخدمين فقط
        )
        
        update.message.reply_text(stats_message, parse_mode='Markdown')
        return
        
    elif text == "📢 رسالة جماعية":
        if str(user.id) != ADMIN_ID:
            update.message.reply_text("⚠️ عذراً، هذه الميزة متاحة فقط للمشرف.")
            return
            
        context.user_data['waiting_for_broadcast'] = True
        update.message.reply_text(
            "📢 *إرسال رسالة جماعية*\n\n"
            "أرسل الرسالة التي تريد إرسالها لجميع المستخدمين.",
            parse_mode='Markdown'
        )
        return

    # التحقق من انتظار رسالة جماعية
    if str(user.id) == ADMIN_ID and context.user_data.get('waiting_for_broadcast'):
        context.user_data['waiting_for_broadcast'] = False
        broadcast_message = text
        sent_count = 0
        failed_count = 0
        
        update.message.reply_text("جاري إرسال الرسالة للمستخدمين...")
        
        for uid in users_data['users']:
            try:
                context.bot.send_message(
                    chat_id=uid,
                    text=broadcast_message,
                    parse_mode='Markdown'
                )
                sent_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(f"Error sending broadcast to {uid}: {str(e)}")
        
        update.message.reply_text(
            f"✅ تم إرسال الرسالة بنجاح!\n\n"
            f"📤 تم الإرسال: {sent_count}\n"
            f"❌ فشل الإرسال: {failed_count}"
        )
        return

    keyboard = [
        [KeyboardButton("📥 تحميل من يوتيوب"), KeyboardButton("📥 تحميل من سناب شات")],
        [KeyboardButton("ℹ️ معلوماتي")]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    message = (
        f"👋 مرحباً {user.first_name}!\n"
        "أنا بوت تحميل الفيديوهات 🎥\n"
        "يمكنني تحميل الفيديوهات من:\n"
        "• يوتيوب 📺\n"
        "• سناب شات 👻\n\n"
        "فقط أرسل لي رابط الفيديو وسأقوم بتحميله لك! 😊"
    )
    
    if user.id not in users_data['users']:
        update.message.reply_text(message, reply_markup=reply_markup)

def handle_url(update: Update, context: CallbackContext):
    """معالجة الروابط المرسلة للبوت"""
    if not update.message:
        return

    url = update.message.text.strip()
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    try:
        if is_snapchat_url(url):
            status_message = update.message.reply_text("⏳ جاري تحميل الفيديو من سناب شات...")
            try:
                filename, title = download_snapchat(url, user_id)
                if filename and os.path.exists(filename):
                    # إرسال الفيديو
                    with open(filename, 'rb') as video_file:
                        update.message.reply_video(
                            video=video_file,
                            caption=f"✅ تم التحميل بنجاح!\n🎥 {title}",
                            supports_streaming=True
                        )
                    status_message.delete()
                    # حذف الملف بعد الإرسال
                    os.remove(filename)
                else:
                    status_message.edit_text("❌ عذراً، فشل تحميل الفيديو. الرجاء المحاولة مرة أخرى.")
            except Exception as e:
                logger.error(f"Error downloading Snapchat video: {str(e)}")
                status_message.edit_text("❌ عذراً، حدث خطأ أثناء تحميل الفيديو. الرجاء المحاولة مرة أخرى.")
        
        elif is_youtube_url(url):
            keyboard = [
                [
                    InlineKeyboardButton("🎥 تحميل فيديو", callback_data=f"video_{url}"),
                    InlineKeyboardButton("🎵 تحميل صوت", callback_data=f"audio_{url}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text(
                "🎥 اختر نوع التحميل:",
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Error handling URL: {str(e)}")
        update.message.reply_text("❌ عذراً، حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى.")

def handle_button(update: Update, context: CallbackContext):
    """معالجة الأزرار"""
    query = update.callback_query
    
    try:
        if query.data.startswith('video_') or query.data.startswith('audio_'):
            # استخراج الرابط ونوع التحميل
            download_type, url = query.data.split('_', 1)
            chat_id = query.message.chat_id
            message_id = query.message.message_id
            
            # تحويل رابط Shorts إلى رابط فيديو عادي
            if 'shorts' in url:
                video_id = url.split('/')[-1].split('?')[0]
                url = f'https://www.youtube.com/watch?v={video_id}'
            
            # إنشاء رسالة التقدم الأولية مع شريط التقدم
            initial_progress_text = (
                f"📥 جاري التحميل...\n"
                f"▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱ 0%\n"
                f"⚡️ السرعة: -- MB/s\n"
                f"⏳ الوقت المتبقي: -- ثانية\n"
                f"📊 0/-- MB"
            )
            status_message = query.edit_message_text(initial_progress_text)
            
            # إعداد خيارات التحميل
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best',
                'outtmpl': f'downloads/{chat_id}/%(id)s.%(ext)s',
                'progress_hooks': [lambda d: progress_callback(d, status_message)],
                'merge_output_format': 'mp4',
                'writethumbnail': True,
                'restrictfilenames': True,
                'windowsfilenames': True,
            }
            
            if download_type == 'audio':
                ydl_opts.update({
                    'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                })
            
            # إنشاء مجلد التحميل
            download_path = f'downloads/{chat_id}'
            os.makedirs(download_path, exist_ok=True)
            
            # تحميل الفيديو
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise Exception("فشل في استخراج معلومات الفيديو")
                
                video_id = info.get('id', 'video')
                ext = info.get('ext', 'mp4') if download_type == 'video' else 'mp3'
                filename = os.path.join(download_path, f"{video_id}.{ext}")
                
                # إرسال الملف
                with open(filename, 'rb') as file:
                    caption = f"🎥 {info.get('title', 'Video')}" if download_type == 'video' else f"🎵 {info.get('title', 'Audio')}"
                    
                    if download_type == 'audio':
                        context.bot.send_audio(
                            chat_id=chat_id,
                            audio=file,
                            caption=caption
                        )
                    else:
                        context.bot.send_video(
                            chat_id=chat_id,
                            video=file,
                            caption=caption,
                            supports_streaming=True
                        )
                
                # تحديث إحصائيات المستخدم
                update_user_stats(query.from_user.id, action='youtube')
                
                # حذف الملف بعد الإرسال
                os.remove(filename)
                
                # تحديث رسالة النجاح
                query.edit_message_text("✅ تم التحميل بنجاح!")
        
        else:
            handle_admin_buttons(update, context)
            
    except Exception as e:
        logger.error(f"Error downloading YouTube: {str(e)}")
        query.edit_message_text("❌ عذراً، حدث خطأ أثناء التحميل. الرجاء المحاولة مرة أخرى.")

def handle_admin_buttons(update: Update, context: CallbackContext):
    """معالجة أزرار لوحة تحكم المشرف"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    if user_id != ADMIN_ID:
        query.answer("⛔️ عذراً، هذا الأمر متاح للمشرفين فقط")
        return
    
    query.answer()
    
    if query.data == 'list_users':
        # تحديث حالة المستخدمين
        current_time = datetime.now()
        users_list = []
        active_count = 0
        inactive_count = 0
        
        for uid, user_data in users_data['users'].items():
            # التعامل مع القيم الفارغة للتواريخ
            last_active = user_data.get('last_active')
            if not last_active or not isinstance(last_active, datetime):
                last_active = current_time
            
            try:
                days_inactive = (current_time - last_active).days
            except (TypeError, AttributeError):
                days_inactive = 0
            
            # تحديث حالة المستخدم
            if days_inactive < 7:
                status = 'نشط 🟢'
                active_count += 1
            else:
                status = 'غير نشط 🔴'
                inactive_count += 1
            
            # تحضير اسم المستخدم
            user_name = user_data.get('first_name', '')
            if user_data.get('last_name'):
                user_name += f" {user_data.get('last_name')}"
            user_name = user_name.strip() or "مستخدم مجهول"
            
            # تحضير المعرف
            username = user_data.get('username', '')
            username_display = f"@{username}" if username else "لا يوجد معرف"
            
            users_list.append({
                'name': user_name,
                'username': username_display,
                'user_id': uid,
                'status': status,
                'downloads': {
                    'total': user_data.get('downloads', 0),
                    'youtube': user_data.get('youtube_downloads', 0),
                    'snapchat': user_data.get('snapchat_downloads', 0)
                },
                'interactions': user_data.get('total_interactions', 0),
                'last_active': last_active,
                'join_date': user_data.get('join_date', current_time)
            })
        
        # ترتيب المستخدمين حسب آخر نشاط
        users_list.sort(key=lambda x: x['last_active'], reverse=True)
        
        # إنشاء رسالة الإحصائيات
        stats_message = (
            "👥 إحصائيات المستخدمين:\n"
            "━━━━━━━━━━━━━━\n"
            f"• المستخدمين النشطين: {active_count} 🟢\n"
            f"• المستخدمين غير النشطين: {inactive_count} 🔴\n"
            f"• الإجمالي: {len(users_list)}\n\n"
            "قائمة جميع المستخدمين:\n"
        )
        
        # إرسال رسالة الإحصائيات
        query.edit_message_text(text=stats_message)
        
        # إنشاء قائمة المستخدمين
        current_message = ""
        for i, user in enumerate(users_list, 1):
            try:
                last_active_str = format_time_ago(user['last_active'])
                join_date_str = user['join_date'].strftime('%d-%m-%Y')
            except (TypeError, AttributeError):
                last_active_str = "منذ لحظات"
                join_date_str = datetime.now().strftime('%d-%m-%Y')
            
            user_info = (
                f"{i}. {user['name']}\n"
                f"↳ المعرف: {user['username']}\n"
                f"↳ ID: {user['user_id']}\n"
                f"↳ الحالة: {user['status']}\n"
                f"↳ التحميلات:\n"
                f"   • المجموع: {user['downloads']['total']}\n"
                f"   • يوتيوب: {user['downloads']['youtube']}\n"
                f"   • سناب شات: {user['downloads']['snapchat']}\n"
                f"↳ التفاعلات: {user['interactions']}\n"
                f"↳ آخر نشاط: {last_active_str}\n"
                f"↳ تاريخ الانضمام: {join_date_str}\n\n"
            )
            
            if len(current_message + user_info) > 4000:
                context.bot.send_message(chat_id=query.message.chat_id, text=current_message)
                current_message = user_info
            else:
                current_message += user_info
        
        if current_message:
            keyboard = [[InlineKeyboardButton("🔄 رجوع", callback_data='back_to_menu')]]
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text=current_message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    elif query.data == 'general_stats':
        total_downloads = users_data.get('total_downloads', 0)
        youtube_downloads = sum(user.get('youtube_downloads', 0) for user in users_data['users'].values())
        snapchat_downloads = sum(user.get('snapchat_downloads', 0) for user in users_data['users'].values())
        
        # حساب المستخدمين النشطين وغير النشطين
        current_time = datetime.now()
        active_users = 0
        inactive_users = 0
        
        for user in users_data['users'].values():
            last_active = user.get('last_active')
            if not last_active or not isinstance(last_active, datetime):
                last_active = current_time
            
            try:
                days_inactive = (current_time - last_active).days
                if days_inactive < 7:
                    active_users += 1
                else:
                    inactive_users += 1
            except (TypeError, AttributeError):
                inactive_users += 1
        
        message = (
            "📊 إحصائيات عامة\n"
            f"━━━━━━━━━━━━━━\n"
            f"👥 المستخدمين:\n"
            f"• نشط: {active_users} 🟢\n"
            f"• غير نشط: {inactive_users} 🔴\n"
            f"• الإجمالي: {len(users_data['users'])}\n\n"
            f"📥 التحميلات:\n"
            f"• المجموع: {total_downloads}\n"
            f"• يوتيوب: {youtube_downloads}\n"
            f"• سناب شات: {snapchat_downloads}\n"
        )
        
        keyboard = [[InlineKeyboardButton("🔄 رجوع", callback_data='back_to_menu')]]
        query.edit_message_text(text=message, reply_markup=InlineKeyboardMarkup(keyboard))

def get_back_button():
    """زر الرجوع للقائمة الرئيسية"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔄 رجوع", callback_data='back_to_menu')]])

def display_user_info(update: Update, context: CallbackContext, user_id):
    """عرض معلومات المستخدم"""
    user_data = users_data['users'].get(str(user_id), {})
    if user_data:
        message = (
            f"📱 معلومات المستخدم\n"
            f"━━━━━━━━━━━━━━\n"
            f"🆔 المعرف: {user_id}\n"
            f"👤 الاسم: {user_data.get('first_name', 'غير متوفر')}\n"
            f"🌐 المعرف: @{user_data.get('username', 'غير متوفر')}\n"
            f"📅 تاريخ الانضمام: {user_data.get('join_date').strftime('%d-%m-%Y')}\n"
            f"⭐️ مستخدم مميز: {'نعم' if user_data.get('is_premium') else 'لا'}\n"
            f"🗣 اللغة: {user_data.get('language_code', 'غير محدد')}\n"
            f"⏱ آخر نشاط: {format_time_ago(user_data.get('last_active'))}\n"
            f"📊 إحصائيات التحميل:\n"
            f"   • إجمالي التحميلات: {user_data.get('downloads', 0)}\n"
            f"   • تحميلات يوتيوب: {user_data.get('youtube_downloads', 0)}\n"
            f"   • تحميلات سناب شات: {user_data.get('snapchat_downloads', 0)}\n"
        )
        if isinstance(update, Update):
            update.message.reply_text(message)
        else:
            update.edit_message_text(message, reply_markup=get_back_button())
    else:
        if isinstance(update, Update):
            update.message.reply_text("❌ لم يتم العثور على معلومات المستخدم")
        else:
            update.edit_message_text("❌ لم يتم العثور على معلومات المستخدم", reply_markup=get_back_button())

def progress_callback(d, message):
    if d['status'] == 'downloading':
        try:
            # التحقق من الوقت المنقضي منذ آخر تحديث
            current_time = time.time()
            if hasattr(progress_callback, 'last_update_time'):
                # تحديث كل ثانية فقط
                if current_time - progress_callback.last_update_time < 1:
                    return
            progress_callback.last_update_time = current_time

            total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            
            if total > 0:
                # تقريب النسبة المئوية إلى رقمين عشريين
                percentage = round((downloaded / total) * 100, 1)
                
                # إنشاء شريط التقدم
                bar_length = 20
                filled_length = int(bar_length * percentage / 100)
                bar = '▰' * filled_length + '▱' * (bar_length - filled_length)
                
                # حساب وتقريب السرعة
                speed = d.get('speed', 0)
                if speed:
                    speed = round(speed/1024/1024, 1)  # تقريب السرعة إلى رقم عشري واحد
                    speed_str = f"{speed} MB/s"
                else:
                    speed_str = "-- MB/s"
                
                # حساب الوقت المتبقي
                eta = d.get('eta', 0)
                if eta:
                    if eta > 60:
                        minutes = eta // 60
                        seconds = eta % 60
                        eta_str = f"{minutes} دقيقة و {seconds} ثانية"
                    else:
                        eta_str = f"{eta} ثانية"
                else:
                    eta_str = "-- ثانية"
                
                # تقريب حجم الملف
                total_mb = round(total/1024/1024, 1)
                downloaded_mb = round(downloaded/1024/1024, 1)
                
                progress_text = (
                    f"📥 جاري التحميل...\n"
                    f"{bar} {percentage}%\n"
                    f"⚡️ السرعة: {speed_str}\n"
                    f"⏳ الوقت المتبقي: {eta_str}\n"
                    f"📊 {downloaded_mb}/{total_mb} MB"
                )
                
                # تحديث الرسالة فقط إذا تغير النص
                if hasattr(progress_callback, 'last_message'):
                    if progress_callback.last_message != progress_text:
                        try:
                            message.edit_text(progress_text)
                            progress_callback.last_message = progress_text
                        except Exception:
                            pass  # تجاهل أخطاء تحديث الرسالة
                else:
                    try:
                        message.edit_text(progress_text)
                        progress_callback.last_message = progress_text
                    except Exception:
                        pass
                    
        except Exception as e:
            logging.error(f"Error in progress callback: {str(e)}")

def download_snapchat(url, user_id):
    """تحميل فيديو من سناب شات"""
    try:
        temp_dir = os.path.join(os.getcwd(), f'downloads_{user_id}')
        os.makedirs(temp_dir, exist_ok=True)
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Snapchat video')
            filename = ydl.prepare_filename(info)
            
            if not os.path.exists(filename):
                possible_files = os.listdir(temp_dir)
                for file in possible_files:
                    if file.startswith(os.path.splitext(os.path.basename(filename))[0]):
                        filename = os.path.join(temp_dir, file)
                        break
            
            # تحديث إحصائيات المستخدم
            update_user_stats(user_id, 'download')
            update_user_stats(user_id, 'snapchat')
            
            return filename, title
            
    except Exception as e:
        logger.error(f"Error downloading Snapchat video: {str(e)}")
        raise

def is_youtube_url(url):
    """التحقق من رابط يوتيوب"""
    return any(domain in url.lower() for domain in ['youtube.com', 'youtu.be'])

def is_snapchat_url(url):
    """التحقق من رابط سناب شات"""
    return 'snapchat.com' in url.lower()

def start(update: Update, context: CallbackContext):
    """تحديث إحصائيات المستخدم عند بدء استخدام البوت"""
    user_id = str(update.message.from_user.id)
    
    # التحقق مما إذا كان المستخدم جديداً
    is_new_user = user_id not in users_data['users']
    
    update_user_stats(update)
    
    # إرسال رسالة الترحيب فقط للمستخدمين الجدد
    if is_new_user:
        keyboard = [
            [KeyboardButton("📥 تحميل من يوتيوب"), KeyboardButton("📥 تحميل من سناب شات")],
            [KeyboardButton("ℹ️ معلوماتي")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        message = (
            f"👋 مرحباً {update.message.from_user.first_name}!\n"
            "أنا بوت تحميل الفيديوهات 🎥\n"
            "يمكنني تحميل الفيديوهات من:\n"
            "• يوتيوب 📺\n"
            "• سناب شات 👻\n\n"
            "فقط أرسل لي رابط الفيديو وسأقوم بتحميله لك! 😊"
        )
        
        update.message.reply_text(message, reply_markup=reply_markup)

def search_user(update: Update, context: CallbackContext):
    if not str(update.message.from_user.id) == ADMIN_ID:
        update.message.reply_text("⛔️ عذراً، هذا الأمر متاح للمشرفين فقط")
        return

    if len(context.args) == 0:
        update.message.reply_text("⚠️ الرجاء إدخال معرف المستخدم أو اسم المستخدم للبحث")
        return
    
    search_term = context.args[0].lower()
    found_users = []
    
    for user_id, user_data in users_data['users'].items():
        if (str(user_id).lower() == search_term or 
            str(user_data.get('username', '')).lower() == search_term.lstrip('@') or 
            str(user_data.get('first_name', '')).lower().startswith(search_term)):
            found_users.append((user_id, user_data))
    
    if found_users:
        for user_id, _ in found_users:
            display_user_info(update, context, user_id)
    else:
        update.message.reply_text("❌ لم يتم العثور على المستخدم")

def admin_dashboard(update: Update, context: CallbackContext):
    if not str(update.message.from_user.id) == ADMIN_ID:
        update.message.reply_text("⛔️ عذراً، هذا الأمر متاح للمشرفين فقط")
        return

    keyboard = [
        [InlineKeyboardButton("👥 قائمة المستخدمين", callback_data='list_users')],
        [InlineKeyboardButton("📊 إحصائيات عامة", callback_data='general_stats')],
        [InlineKeyboardButton("🔍 بحث عن مستخدم", callback_data='search_user')],
        [InlineKeyboardButton("📢 رسالة جماعية", callback_data='broadcast')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("🎛 لوحة تحكم المشرف\nاختر ما تريد عرضه:", reply_markup=reply_markup)

def main():
    """تشغيل البوت"""
    # تحميل بيانات المستخدمين عند بدء البوت
    load_users_data()
    
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(CallbackQueryHandler(handle_button))  # معالج واحد لجميع الأزرار
    
    updater.start_polling(drop_pending_updates=True)
    logger.info("تم تشغيل البوت!")
    updater.idle()

if __name__ == '__main__':
    main()
